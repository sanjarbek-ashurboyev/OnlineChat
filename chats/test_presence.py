from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import redis
from channels.layers import get_channel_layer
from channels_redis.core import RedisChannelLayer
from django.test import SimpleTestCase

from chats import presence
from test_helpers import FakePresenceMixin


class PresenceTests(FakePresenceMixin, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.clock = 1000.0
        patcher = mock.patch('chats.presence.now', lambda: self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ping_for(self, seconds, user_id, channel):
        """A live tab: one ping every 30 s, like assets/app.js."""
        for _ in range(int(seconds // 30)):
            self.clock += 30
            presence.refresh(user_id, channel)

    def test_an_open_socket_counts_until_it_closes(self):
        presence.mark_online(1, 'tab')
        self.assertEqual((presence.socket_count(1), presence.is_online(1)), (1, True))

        presence.mark_offline(1, 'tab')
        self.assertEqual((presence.socket_count(1), presence.is_online(1)), (0, False))

    def test_a_socket_that_keeps_pinging_keeps_counting(self):
        presence.mark_online(1, 'tab')
        self.ping_for(600, 1, 'tab')
        self.assertEqual(presence.socket_count(1), 1)

    def test_a_dead_socket_stops_counting_even_while_another_tab_pings(self):
        # A crashed consumer or a killed process never runs disconnect(), so its entry stays
        # behind. It used to live as long as any other tab kept pinging, and 5 of them
        # locked the user out (session 011).
        presence.mark_online(1, 'dead')
        presence.mark_online(1, 'live')
        self.ping_for(120, 1, 'live')

        self.assertEqual(presence.socket_count(1), 1)
        self.assertTrue(presence.is_online(1))

    def test_a_user_whose_only_socket_died_goes_offline(self):
        presence.mark_online(1, 'dead')
        self.clock += presence.TTL_SECONDS + 1
        self.assertFalse(presence.is_online(1))

    def test_admit_lets_sockets_in_up_to_the_limit(self):
        self.assertEqual([presence.admit(1, f'tab-{n}', 2) for n in range(3)], [True, True, False])
        self.assertEqual(presence.socket_count(1), 2)
        self.assertTrue(presence.admit(2, 'tab', 2), 'the limit is per user')

    def test_admit_does_not_count_dead_sockets(self):
        presence.mark_online(1, 'dead')
        self.clock += presence.TTL_SECONDS + 1
        self.assertTrue(presence.admit(1, 'new', 1))

    def test_online_map_ages_out_dead_sockets_too(self):
        presence.mark_online(1, 'dead')
        presence.mark_online(2, 'live')
        self.ping_for(120, 2, 'live')
        self.assertEqual(presence.online_map([1, 2, 3]), {1: False, 2: True, 3: False})


class PresenceOnRealRedisTests(SimpleTestCase):
    """The same rules against a real Redis, so the fake can't hide a mistake. Runs in the
    CI job test-postgres-redis; skipped on the SQLite settings."""

    USER = 10**12  # an id no real user has

    def setUp(self):
        if not isinstance(get_channel_layer(), RedisChannelLayer):
            self.skipTest('needs Redis')
        presence._client = None  # a FakePresenceMixin test may have left a fake behind
        try:
            presence.client().ping()
        except redis.RedisError:
            self.skipTest('Redis is not reachable')
        self.addCleanup(presence.client().delete, presence.key(self.USER))
        self.clock = 1000.0
        patcher = mock.patch('chats.presence.now', lambda: self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_dead_socket_stops_counting_even_while_another_tab_pings(self):
        presence.mark_online(self.USER, 'dead')
        presence.mark_online(self.USER, 'live')
        for _ in range(4):
            self.clock += 30
            presence.refresh(self.USER, 'live')

        self.assertEqual(presence.socket_count(self.USER), 1)
        self.assertEqual(presence.online_map([self.USER]), {self.USER: True})
        presence.mark_offline(self.USER, 'live')
        self.assertFalse(presence.is_online(self.USER))

    def test_admit_stops_at_the_limit_even_when_called_at_once(self):
        # Codex audit M-01: the real Lua script, from 8 threads at the same moment.
        with ThreadPoolExecutor(max_workers=8) as pool:
            admitted = list(pool.map(lambda n: presence.admit(self.USER, f'tab-{n}', 5), range(8)))

        self.assertEqual(sum(admitted), 5)
        self.assertEqual(presence.socket_count(self.USER), 5)

    def test_admit_does_not_count_dead_sockets(self):
        presence.mark_online(self.USER, 'dead')
        self.clock += presence.TTL_SECONDS + 1
        self.assertTrue(presence.admit(self.USER, 'new', 1))
        self.assertEqual(presence.socket_count(self.USER), 1)
