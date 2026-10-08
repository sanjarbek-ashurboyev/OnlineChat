"""Who is connected right now, tracked in Redis.

One Redis set per user, holding the channel name of each open socket. The user
is online when that set is non-empty. Each set carries a TTL so a crashed
worker's leftovers expire instead of pinning someone online forever.

Redis db 2 — the channel layer uses 0 and the Django cache uses 1.
"""

import logging

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


def key(user_id):
    return f'presence:{user_id}'


def mark_online(user_id, channel_name):
    try:
        pipe = client().pipeline()
        pipe.sadd(key(user_id), channel_name)
        pipe.expire(key(user_id), TTL_SECONDS)
        pipe.execute()
    except redis.RedisError:
        logger.exception('presence: mark_online failed for user %s', user_id)


def refresh(user_id):
    """Push the expiry back; called on every ping so a quiet socket stays online."""
    try:
        client().expire(key(user_id), TTL_SECONDS)
    except redis.RedisError:
        logger.exception('presence: refresh failed for user %s', user_id)


def mark_offline(user_id, channel_name):
    try:
        client().srem(key(user_id), channel_name)
    except redis.RedisError:
        logger.exception('presence: mark_offline failed for user %s', user_id)


def is_online(user_id):
    try:
        return client().scard(key(user_id)) > 0
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
        pipe = client().pipeline()
        for user_id in ids:
            pipe.scard(key(user_id))
        return {uid: count > 0 for uid, count in zip(ids, pipe.execute(), strict=True)}
    except redis.RedisError:
        logger.exception('presence: online_map failed')
        return {uid: False for uid in ids}
