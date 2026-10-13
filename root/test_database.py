"""T-13 (PERF-2): database calls reuse pooled connections instead of opening a new one each time."""
import threading
import unittest

import psycopg
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from django.conf import settings
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

    def test_a_pool_full_of_dead_connections_recovers(self):
        # A Postgres restart (or failover) kills the server side of every pooled connection. The pool can't know
        # until it uses one: without a check the next request got a dead one, and with only the pool's default check
        # a full pool of dead ones outlasted the 5 s timeout. Either way the request failed.
        size = settings.DATABASES['default']['OPTIONS']['pool']['max_size']
        self.addCleanup(connection.close_pool)  # the next test gets a fresh pool, not these 10 connections
        everyone_holds_one = threading.Barrier(size)
        errors = []

        def hold_a_connection():
            try:
                backend_pid()
                everyone_holds_one.wait(timeout=10)
            except Exception as error:
                errors.append(error)
            finally:
                connection.close()  # back to the pool, like at the end of every request

        connection.close()  # the test's own connection would take one of the slots
        threads = [threading.Thread(target=hold_a_connection) for _ in range(size)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])

        with psycopg.connect(**connection.get_connection_params(), autocommit=True) as admin:
            killed = admin.execute(
                'SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity'
                " WHERE datname = current_database() AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
            ).fetchone()[0]
        self.assertGreaterEqual(killed, size)

        self.assertIsInstance(backend_pid(), int)
