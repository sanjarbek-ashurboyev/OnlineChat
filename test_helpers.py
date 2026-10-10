"""Shared builders for the test suite."""
from unittest import mock

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
from chats import presence

PASSWORD = 'Str0ng-pass!'


def phone(n):
    return f'+9989012345{n:02d}'


def make_user(n=1, **extra):
    return User.objects.create_user(phone_number=phone(n), password=PASSWORD,
                                    first_name=f'User {n}', **extra)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def token_for(user):
    return str(AccessToken.for_user(user))


class FakeRedis:
    """The few commands chats.presence uses, backed by dicts."""

    def __init__(self):
        self.zsets = {}

    def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    def zrem(self, key, *members):
        for member in members:
            self.zsets.get(key, {}).pop(member, None)

    @staticmethod
    def _in_range(score, low, high):
        """Redis score ranges: inclusive, or exclusive with a '(' prefix; '-inf'/'+inf' allowed."""
        def bound(value):
            value = str(value)
            return (value[1:], True) if value.startswith('(') else (value, False)
        (low, low_open), (high, high_open) = bound(low), bound(high)
        above = score > float(low) if low_open else score >= float(low)
        below = score < float(high) if high_open else score <= float(high)
        return above and below

    def zcount(self, key, low, high):
        return sum(self._in_range(s, low, high) for s in self.zsets.get(key, {}).values())

    def zremrangebyscore(self, key, low, high):
        scores = self.zsets.get(key, {})
        for member in [m for m, s in scores.items() if self._in_range(s, low, high)]:
            del scores[member]

    def expire(self, key, seconds):
        pass

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis):
        self.redis, self.calls = redis, []

    def __getattr__(self, name):
        def queue(*args):
            self.calls.append((name, args))
        return queue

    def execute(self):
        return [getattr(self.redis, name)(*args) for name, args in self.calls]


class FakePresenceMixin:
    """Points chats.presence at an in-memory Redis for the duration of each test."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(presence, '_client', FakeRedis())
        self.redis = patcher.start()
        self.addCleanup(patcher.stop)
