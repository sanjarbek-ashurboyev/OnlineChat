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
    """The few set commands chats.presence uses, backed by a dict."""

    def __init__(self):
        self.sets = {}

    def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)

    def srem(self, key, member):
        self.sets.get(key, set()).discard(member)

    def scard(self, key):
        return len(self.sets.get(key, ()))

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
