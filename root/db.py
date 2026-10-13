from psycopg_pool import ConnectionPool


def check_pooled_connection(conn):
    """Test a pooled connection before a request gets it; on a dead one, drop every dead one.

    After a Postgres restart every idle connection in the pool is dead. The pool's own check finds them one at a
    time and waits 0 s, then 1 s, 2 s, 4 s... between tries, so a pool of 10 dead ones outlasted the 5 s timeout and the
    request failed. `pool.check()` tests all idle connections at once and replaces the dead ones.
    """
    try:
        ConnectionPool.check_connection(conn)
    except Exception:
        from django.db import connections

        connections['default'].pool.check()
        raise
