from psycopg_pool import ConnectionPool


def check_pooled_connection(conn):
    """Test a pooled connection before a request gets it; on a dead one, replace every idle one.

    After a Postgres restart every idle connection in the pool is dead. The pool's own check finds them one at a
    time and waits 0 s, then 1 s, 2 s, 4 s... between tries, so a pool of 10 dead ones outlasted the 5 s timeout and the
    request failed. `pool.drain()` closes all idle connections at once, without testing them, and opens new ones in
    the pool's background workers. (`pool.check()` tested them one by one on this request's thread, holding them all
    out of the pool meanwhile: one that hung stalled every request, Codex review of #45.)
    """
    try:
        ConnectionPool.check_connection(conn)
    except Exception:
        from django.db import connections

        connections['default'].pool.drain()
        raise
