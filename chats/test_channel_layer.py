"""The real Redis channel layer. Skipped on the SQLite settings, which use the in-memory layer;
the CI job test-postgres-redis runs it."""
import asyncio

from channels.layers import get_channel_layer
from channels_redis.core import RedisChannelLayer
from django.test import SimpleTestCase


class RedisChannelLayerTests(SimpleTestCase):
    def setUp(self):
        self.layer = get_channel_layer()
        if not isinstance(self.layer, RedisChannelLayer):
            self.skipTest('needs the Redis channel layer')

    async def test_a_quiet_channel_does_not_crash_the_reader(self):
        # A socket with nothing to receive waits in BZPOPMIN for brpop_timeout (5 s). redis-py 8
        # defaults to a 5 s socket timeout, which fires first and crashed every idle consumer.
        channel = await self.layer.new_channel()
        with self.assertRaises(asyncio.TimeoutError, msg='our own wait ends it, not a Redis error'):
            await asyncio.wait_for(self.layer.receive(channel), timeout=self.layer.brpop_timeout + 2)

    async def test_a_burst_of_group_changes_waits_for_a_free_connection(self):
        # 2,000 sockets closing at once run 2,000 group_discards together. redis-py's pool holds 100 connections
        # and raised MaxConnectionsError for the rest instead of waiting: 289 errors at the end of a 2,000-user
        # load test (session 032). Each call must get a connection, even if it has to wait for one.
        group = 'burst-test'
        channels = [await self.layer.new_channel() for _ in range(300)]
        await asyncio.gather(*(self.layer.group_add(group, channel) for channel in channels))
        await asyncio.gather(*(self.layer.group_discard(group, channel) for channel in channels))
