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
