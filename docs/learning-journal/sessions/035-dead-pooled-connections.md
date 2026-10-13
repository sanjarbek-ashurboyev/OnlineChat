# 035 · The pool handed out dead connections after a Postgres restart

- **Date:** 2026-10-13 · **Phase:** Stage 1
- **Task:** Codex review of PRs #38–#43, finding "pool hands out dead DB connections" (follow-up to T-13, session 032)
  · **Branch:** `t-13-conn-health-checks`
- **Files:** `root/db.py` (new), `root/settings.py`, `root/test_database.py`, docs
- **Objective:** after Postgres restarts, the next requests must not fail because the pool gives them a connection
  whose server side is gone.

## What was done
1. **Reproduced it on `main` (`35eb53a`)** with a test: fill the pool, kill every connection on the server
   (`pg_terminate_backend`, what a restart does to them), then make one query. Result: **error**,
   `OperationalError: terminating connection due to administrator command`, and the *next* test failed the same way,
   because it got the next dead connection.
2. **Tried the finding's suggested fix first**, `CONN_HEALTH_CHECKS = True`. It's not enough:
   - 3 dead connections in the pool: the request succeeded, but only after **2.9 s**.
   - 10 dead connections (a full pool, `max_size`): the request **failed** after 5 s,
     `couldn't get a connection after 5.00 sec`.
3. **Read why** in psycopg_pool (`_getconn_with_check_loop`): it tests one connection, and if that one is dead it
   throws it away and tries the next one, waiting 0 s, then ~1 s, ~2 s, ~4 s between tries. With 10 dead ones,
   0 + 1 + 2 + 4 s is already past our 5 s `timeout`. *(Confirmed: from the source and the timings above.)*
4. **Fix:** our own check, `root/db.py` `check_pooled_connection`. It tests the connection like the pool's default
   check; if that one is dead, it also calls `pool.check()`, which tests **every** idle connection at once and replaces
   the dead ones. The pool's next try (the one with no wait) then gets a fresh connection.
5. **Test** `test_a_pool_full_of_dead_connections_recovers` (`root/test_database.py`): 10 threads each hold a
   connection at once (a `Barrier`), so the pool really has 10; all are killed; one query must work.
   - `main`: error (dead connection). With `CONN_HEALTH_CHECKS` only: error (pool timeout). With the fix: pass.
6. **Real server check:** Daphne on `:8002`, six `GET /readyz`, `docker compose restart db`, six more.
   - `main`: `503 503 503 200 200 200` after the restart. Fix: `200 200 200 200 200 200`.
7. **Recovery time with the fix**, 10 dead connections: about **18 ms** for the first query (the probe's query
   sleeps 200 ms; the whole call took 218 ms).
8. **Overhead re-measured** (see Results).
9. **Results:** `make test` **168 run, OK (skipped=18)** (203 found; a skipped browser class counts once); real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True`
   **203 OK**; Ruff 0.16.10 clean.

**Not done:** no load test. The check's cost was measured directly (below); near the ceiling a load test can't see a
difference this small (P-37).

## Results

**One database call, as the socket makes it** (`database_sync_to_async`, 1,000 calls per row, 4 interleaved pairs)
| | p50 | p95 | p99 |
|---|---:|---:|---:|
| No check | 1.02–1.72 ms | 1.83–2.18 ms | 2.09–2.39 ms |
| Check on every checkout | 1.17–2.17 ms | 2.41–2.95 ms | 2.88–3.53 ms |

So the check costs about **+0.6–0.8 ms at p95** per call: one extra round trip (an empty query). The Mac was busy
(load average 3.4–4.3, 14 minutes after a reboot): the same "no check" call was 0.67 ms p95 in session 032, so compare
the rows with each other, not with that session.

## Concepts

### A dead pooled connection
- **Simple definition:** a connection the pool thinks is open, but whose other end (the Postgres server process) is
  gone. The first query on it fails.
- **How it happens:** Postgres restarts (an upgrade, a crash, a failover to a standby), a firewall drops idle
  connections, or an admin kills sessions. The pool isn't told; it only finds out when it uses the connection.
- **Example:** before the restart the pool holds 3 open connections. The restart kills all 3 on the server side.
  The next 3 requests each get one of them and fail with a 500 (or `/readyz` says 503), and only then the pool
  replaces them.

### Checking a connection on checkout
Before handing a connection to a request, the pool sends an empty query. Dead → throw it away and try another.
It costs one round trip on *every* checkout, even when nothing is wrong. That's the price of never handing out a
dead one. Full guide: [connection pools](../concepts/connection-pools.md).

## Walkthrough

`root/db.py`:
```python
def check_pooled_connection(conn):
    try:
        ConnectionPool.check_connection(conn)
    except Exception:
        from django.db import connections

        connections['default'].pool.check()
        raise
```
- `ConnectionPool.check_connection` is psycopg's own check (an empty query). It's what `CONN_HEALTH_CHECKS` would
  have used.
- On a dead connection we call `pool.check()`, then **re-raise**: the raise tells the pool "this one is dead", and the
  pool throws it away and tries again.
- `pool.check()` uses the plain `check_connection`, not ours, so it can't call itself in a loop.
- `django.db` is imported inside the function: `root/settings.py` imports this module, so loading the settings
  doesn't also load Django's database layer (which is configured *from* those settings).

`root/settings.py`:
```python
'OPTIONS': {'pool': {'min_size': 2, 'max_size': 10, 'timeout': 5, 'check': check_pooled_connection}},
```
Django passes everything under `pool` to psycopg's `ConnectionPool`. It only fills in `check` itself (from
`CONN_HEALTH_CHECKS`) when we didn't set one, so we don't set `CONN_HEALTH_CHECKS`: it would do nothing.

The test:
- `connection.close()` first: the test's own connection would take one of the 10 slots, and the 10th thread would
  wait 5 s and time out. (The first version of the test did exactly that. Errors in a thread don't fail a test, so
  the threads now collect them and the test asserts the list is empty.)
- `self.addCleanup(connection.close_pool)`: the test leaves 10 connections in the pool. The older pool test asserts
  "20 calls use fewer than 5 connections" and failed after it, since the pool hands its connections out in turn. A
  fresh pool for the next test fixes that.

## Problems
- **The suggested fix didn't fix it.** `CONN_HEALTH_CHECKS = True` passed a test with 3 dead connections (slowly) and
  failed with 10. → [P-38](../problems-and-solutions.md#p-38--conn_health_checks-still-failed-with-a-pool-full-of-dead-connections)

## Decisions
- Check on every checkout, and on a dead one drop them all: [decision 015](../decisions/015-check-pooled-connections.md).

## What I should remember
- A pool only learns a connection is dead by using it. Something has to check.
- "The setting is on" isn't "the bug is fixed": test the worst case (a *full* pool), not only the easy one.
- A test that leaves shared state behind (a full pool) can break the *next* test. Clean it up.

## Review questions
1. Why did the request after a Postgres restart fail, when Postgres was already back up?
2. With `CONN_HEALTH_CHECKS = True`, why did 3 dead connections cost ~3 s, and 10 fail?
3. What does `check_pooled_connection` do differently, and why does it still raise?
4. What does the fix cost when nothing is wrong?
5. Why does the test close its own connection before starting the 10 threads?

<details><summary>Answer key</summary>

1. The pool still held connections opened *before* the restart. Their server processes were gone, but the pool
   didn't know until a request used one.
2. The pool tests one connection at a time and waits between tries: 0 s, ~1 s, ~2 s, ~4 s. Three dead ones: 0 + 1 +
   2 ≈ 3 s. Ten: after 0 + 1 + 2 + 4 = 7 s it's past the 5 s timeout, so the request fails.
3. When it finds one dead connection, it tests all the idle ones at once (`pool.check()`) and replaces the dead ones.
   It still raises so the pool throws away *this* dead connection and tries again; that next try has no wait and gets
   a fresh one.
4. One extra round trip per checkout: about +0.6–0.8 ms at p95 on this Mac.
5. The pool holds at most 10. If the test's own connection kept one, only 9 would be free, and the 10th thread would
   wait 5 s and fail.
</details>

## Next steps
- The two High findings from the same review: a refresh token usable twice at once, and logout from a stale tab.
- If the check's cost ever matters (many calls per message), check only connections that sat idle for a while.
