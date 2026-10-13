"""T-13 (PERF-2): database calls reuse pooled connections instead of opening a new one each time."""
import unittest

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from django.db import connection
from django.test import TransactionTestCase


def backend_pid():
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_backend_pid()')
        return cursor.fetchone()[0]


class ConnectionPoolTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != 'postgresql':
            raise unittest.SkipTest('the pool is a PostgreSQL feature')

    def test_socket_style_calls_share_a_few_connections(self):
        # database_sync_to_async closes the connection after every call. Without a pool each of these
        # calls was a new Postgres process (a new pid, ~6.8 ms to open); with it, a few are reused.
        # How many exactly is the pool's business (the test's own connection comes from it too).
        pids = {async_to_sync(database_sync_to_async(backend_pid))() for _ in range(20)}
        self.assertLess(len(pids), 5, f'{len(pids)} different connections for 20 calls')
