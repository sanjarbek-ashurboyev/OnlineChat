"""Settings for the test suite: no PostgreSQL or Redis needed.

    python manage.py test --settings=root.settings_test
"""
import os

# settings.py reads the database credentials with os.environ[...], so they must exist.
for name in ('DB_NAME', 'DB_USER', 'DB_PASSWORD'):
    os.environ.setdefault(name, 'unused-in-tests')
os.environ.setdefault('DJANGO_SECRET_KEY', 'test-only-secret-key-that-is-long-enough')

from root.settings import *  # noqa: E402,F403

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}

# Messages, read receipts and presence pings go through this; it needs no Redis.
CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}

# The lookup throttle counts requests in the cache.
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

# The WebSocket origin check compares against this.
ALLOWED_HOSTS = ['localhost']

# DEBUG is off here, so production's HTTPS redirect is on; the test client speaks plain HTTP.
SECURE_SSL_REDIRECT = False

# Fast hashing: the suite creates many users.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
