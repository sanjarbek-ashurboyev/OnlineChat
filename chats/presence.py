"""Who is connected right now, tracked in Redis.

One sorted set per user: each open socket's channel name, scored with the time
of its last ping. A socket counts while that time is under TTL_SECONDS old, so
an entry left behind by a crashed consumer or a killed process ages out on its
own, even while the user's other tabs keep pinging. The key's own TTL only
cleans up users who have gone quiet altogether.

Redis db 2 — the channel layer uses 0 and the Django cache uses 1.
"""

import logging
import time

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

TTL_SECONDS = 90

_client = None


def client():
    global _client
    if _client is None:
        _client = redis.Redis.from_url(f'{settings.REDIS_URL}/2',
                                       decode_responses=True)
    return _client


def now():
    """The clock presence uses; tests freeze it."""
    return time.time()


def key(user_id):
    # Not 'presence:': those keys are plain sets, and the new commands would fail on them.
    return f'online:{user_id}'


def _touch(user_id, channel_name):
    pipe = client().pipeline()
    pipe.zadd(key(user_id), {channel_name: now()})
    pipe.expire(key(user_id), TTL_SECONDS)
    pipe.execute()


def mark_online(user_id, channel_name):
    try:
        _touch(user_id, channel_name)
    except redis.RedisError:
        logger.exception('presence: mark_online failed for user %s', user_id)


def refresh(user_id, channel_name):
    """Called on every ping, so a quiet socket stays online. Only this socket's entry."""
    try:
        _touch(user_id, channel_name)
    except redis.RedisError:
        logger.exception('presence: refresh failed for user %s', user_id)


def mark_offline(user_id, channel_name):
    try:
        client().zrem(key(user_id), channel_name)
    except redis.RedisError:
        logger.exception('presence: mark_offline failed for user %s', user_id)


def _live_since():
    return now() - TTL_SECONDS


def socket_count(user_id):
    """Open sockets for this user. 0 when Redis fails, so connecting still works."""
    try:
        pipe = client().pipeline()
        pipe.zremrangebyscore(key(user_id), '-inf', f'({_live_since()}')  # drop dead entries
        pipe.zcount(key(user_id), _live_since(), '+inf')
        return pipe.execute()[1]
    except redis.RedisError:
        logger.exception('presence: socket_count failed for user %s', user_id)
        return 0


def is_online(user_id):
    try:
        return client().zcount(key(user_id), _live_since(), '+inf') > 0
    except redis.RedisError:
        # Degrade to "offline" rather than failing the request.
        logger.exception('presence: is_online failed for user %s', user_id)
        return False


def online_map(user_ids):
    """{user_id: bool} for many users in one round trip."""
    ids = list(user_ids)
    if not ids:
        return {}
    try:
        since = _live_since()
        pipe = client().pipeline()
        for user_id in ids:
            pipe.zcount(key(user_id), since, '+inf')
        return {uid: count > 0 for uid, count in zip(ids, pipe.execute(), strict=True)}
    except redis.RedisError:
        logger.exception('presence: online_map failed')
        return {uid: False for uid in ids}
