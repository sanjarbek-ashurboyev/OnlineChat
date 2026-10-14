"""T-13 (PERF-2): database calls reuse pooled connections instead of opening a new one each time."""
import socket
import threading
import time
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


def shut(sock):
    """Close a socket that another thread may be blocked on (`recv`, `accept`).

    On Linux, `close()` alone doesn't wake that thread, and the connection stays open as long as it waits: here,
    forever, so Postgres kept the sessions and couldn't drop the test database (CI). `shutdown()` wakes it.
    """
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass  # not connected (a listener on macOS), or already closed
    sock.close()


class HangingProxy:
    """A TCP proxy in front of Postgres that can make one connection hang: the server stays up and the request gets
    through, but no answer ever comes back, like a stuck backend or a network that silently drops packets. The hang ends
    (the connection drops) when the proxy closes."""

    def __init__(self, host, port):
        self.upstream = (host, port)
        self.listener = socket.create_server(('127.0.0.1', 0))
        self.port = self.listener.getsockname()[1]
        self.hung_ports = set()
        self.closed = threading.Event()
        self.sockets = []
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while True:
            try:
                client, (_, client_port) = self.listener.accept()
            except OSError:
                return  # closed
            server = socket.create_connection(self.upstream)
            self.sockets += [client, server]
            threading.Thread(target=self.pump, args=(client, server, None), daemon=True).start()
            threading.Thread(target=self.pump, args=(server, client, client_port), daemon=True).start()

    def pump(self, source, target, client_port):
        """Copy bytes one way. `client_port` is set for the server-to-client way, the one a hang holds."""
        try:
            while data := source.recv(65536):
                if client_port in self.hung_ports:
                    self.closed.wait()
                    return
                target.sendall(data)
        except OSError:
            pass
        finally:
            shut(source)
            shut(target)

    def hang(self, conn):
        """From now on, `conn` (a psycopg connection through this proxy) gets no answers."""
        with socket.fromfd(conn.pgconn.socket, socket.AF_INET, socket.SOCK_STREAM) as ours:
            self.hung_ports.add(ours.getsockname()[1])

    def close(self):
        self.closed.set()
        for sock in [self.listener, *self.sockets]:
            shut(sock)


class ConnectionPoolTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != 'postgresql':
            raise unittest.SkipTest('the pool is a PostgreSQL feature')

    def fill_pool(self):
        """Make the pool open every connection it may have (`max_size`), and leave them all idle in it."""
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
        return size

    def through_proxy(self):
        """Send this test's database connections through a `HangingProxy`."""
        params = connection.settings_dict  # shared by every thread's connection
        proxy = HangingProxy(params['HOST'] or 'localhost', int(params['PORT'] or 5432))
        saved = params['HOST'], params['PORT']

        def restore():
            connection.close()
            connection.close_pool()
            params['HOST'], params['PORT'] = saved

        connection.close()
        connection.close_pool()
        params['HOST'], params['PORT'] = '127.0.0.1', str(proxy.port)
        self.addCleanup(restore)
        return proxy

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
        size = self.fill_pool()

        with psycopg.connect(**connection.get_connection_params(), autocommit=True) as admin:
            killed = admin.execute(
                'SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity'
                " WHERE datname = current_database() AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
            ).fetchone()[0]
        self.assertGreaterEqual(killed, size)

        self.assertIsInstance(backend_pid(), int)

    def test_one_hung_connection_doesnt_stall_the_others(self):
        # Codex review of #45: after a restart, the first request to find a dead connection also tested every other
        # idle one, one after the other, on its own thread, holding all of them out of the pool meanwhile. One that
        # hung stopped that request, and every other request waited for a connection until the 5 s timeout.
        proxy = self.through_proxy()
        size = self.fill_pool()
        idle = list(connection.pool._pool)  # the pool's own queue: it hands them out from the left
        self.assertEqual(len(idle), size)
        dead, hung = idle[:5], idle[-1]  # and the 4 between them stay healthy
        with psycopg.connect(**connection.get_connection_params(), autocommit=True) as admin:
            pids = [conn.info.backend_pid for conn in dead]
            admin.execute('SELECT pg_terminate_backend(pid) FROM unnest(%s::int[]) AS pid', [pids])
            while admin.execute('SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(%s)', [pids]).fetchone()[0]:
                time.sleep(0.01)
        proxy.hang(hung)

        took = {}

        def borrow(name):
            started = time.monotonic()
            try:
                backend_pid()
                took[name] = time.monotonic() - started
            except Exception as error:
                took[name] = error
            finally:
                connection.close()

        first = threading.Thread(target=borrow, args=('first',), name='first')
        crowd = [threading.Thread(target=borrow, args=(f'crowd-{n}',), name=f'crowd-{n}') for n in range(20)]
        self.addCleanup(lambda: [thread.join() for thread in [first, *crowd]])
        self.addCleanup(proxy.close)  # ends the hang (runs before the join above)
        first.start()
        time.sleep(0.3)  # its dead connection fails at once; this is when it deals with the others
        for thread in crowd:
            thread.start()
        for thread in [first, *crowd]:
            thread.join(timeout=8)  # longer than the pool's 5 s timeout

        stuck = [thread.name for thread in [first, *crowd] if thread.is_alive()]
        failed = {name: repr(result) for name, result in took.items() if isinstance(result, Exception)}
        self.assertEqual({'stuck': stuck, 'failed': failed}, {'stuck': [], 'failed': {}})
        self.assertLess(max(took.values()), 2, took)
