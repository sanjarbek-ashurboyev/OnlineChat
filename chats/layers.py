from channels_redis.core import RedisChannelLayer
from redis.asyncio import BlockingConnectionPool


class WaitingRedisChannelLayer(RedisChannelLayer):
    """channels-redis with a pool that waits for a free connection instead of failing.

    The stock pool (redis-py's ConnectionPool, 100 connections per process) raises MaxConnectionsError the moment
    all 100 are busy. 2,000 sockets closing at once run 2,000 group_discards together, and 289 of them failed
    (session 032). This pool queues them; `timeout` (seconds) bounds the wait.
    """

    def create_pool(self, index):
        host = dict(self.hosts[index])
        return BlockingConnectionPool.from_url(host.pop('address'), **host)
