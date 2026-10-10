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
