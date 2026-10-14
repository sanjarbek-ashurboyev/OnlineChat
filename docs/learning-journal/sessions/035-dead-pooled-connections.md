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
- *(Replaced by `pool.drain()` in the follow-up below: `pool.check()` could stall every request.)*
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

---

# Follow-up · Codex review of PR #45: one hung connection stalled everyone

- **Date:** 2026-10-14 · **Branch:** `t-13-conn-health-checks` (same PR, #45)
- **Files:** `root/db.py`, `root/test_database.py`, docs
- **Objective:** Codex blocked the PR: the cleanup above (`pool.check()`) could stall every request when one
  connection hangs. Reproduce it with dead, hung and healthy connections and many requests at once, then replace it.

## What was done
1. **A way to make a connection hang** in a test: `HangingProxy` in `root/test_database.py`, a small TCP proxy between
   Django and Postgres. A "hung" connection gets its request through, but the proxy holds the server's answer. That's
   what a stuck server process or a network silently dropping packets looks like. Killing (`pg_terminate_backend`)
   makes the dead ones, as before.
2. **Reproduced** with `test_one_hung_connection_doesnt_stall_the_others`: fill the pool (10), kill 5, hang 1 (the one
   `pool.check()` tests first), keep 4 healthy. One request, then 20 more 0.3 s later. On the branch as it was:
   - the first request **stuck** in `pool.check()` until the test ended the hang;
   - **all 20** others failed with `couldn't get a connection after 5.00 sec`.
3. **Fix:** `pool.drain()` instead of `pool.check()` in `root/db.py`. Same test: **10 runs of 10 passed**; the first
   request took 15–27 ms, the slowest of the 20 others 6–9 ms. The older test (a pool full of dead connections) still
   passes.
4. **Real server:** Daphne on `:8002`, six `GET /readyz`, `docker compose restart db`, six more:
   `200 200 200 200 200 200` both times.
5. **Overhead re-measured** (Results below): per call, at saturation, and with real chat traffic, the check against
   no check, interleaved.
6. **Rebase:** `origin/main` is still `35eb53a`, which the branch already contains: nothing to rebase.
7. **The Low from the review** (this session said `make test` ran 203) was already corrected in `b893f89`. Checked
   by running `make test` at that commit: **168 run, OK (skipped=18)**, 203 found.
8. **Results:** `make test` **169 run, OK (skipped=19)** (204 found); real Postgres + Redis with
   `REQUIRE_BROWSER_TESTS=True` **204 OK**; `makemigrations --check` no changes; Ruff 0.16.10 clean.

**Not done:**
- A request that is handed the hung connection *itself*, before any drain, still waits as long as the hang lasts.
  Without the check its query would hang the same way, so this PR doesn't make it worse. A client-side time limit
  would need our own socket handling (decision 015).
- The chat-traffic comparison ran at 1,000 online (healthy), not near the ceiling, where one pair of runs can't show a
  difference this small (P-37).

## Results

All on this Mac, the check against the same settings without it (a settings file in `/tmp`, not in the repo),
interleaved. Load average 2.8–5.3 during the first two, 2.8–4.3 during the load tests.

**One database call, as the socket makes it** (`database_sync_to_async(SELECT 1)`, 1,000 calls per row, 4 pairs)
| | p50 | p95 | p99 |
|---|---:|---:|---:|
| No check | 0.93–1.27 ms | 1.58–1.75 ms | 2.00–2.34 ms |
| Check on every checkout | 1.33–1.71 ms | 2.43–2.61 ms | 3.26–3.77 ms |

**Saturation** (40 threads, pool of 10, `SELECT 1` and give the connection back, 5 s, same 4 pairs)
| | calls/s |
|---|---:|
| No check | 5,955–6,028 |
| Check | 3,530–3,575 (−41%) |

**Real chat traffic** (Daphne, `loadtest/run.py --steps 1000 --hold 60`, 1,000 seeded users, 2 pairs)
| Run | sent | message p50 / p95 / p99 | delivery p95 | ping p95 | poll p95 | errors |
|---|---:|---|---:|---:|---:|---:|
| No check 1 | 869 | 18 / 36 / 47 ms | 35 ms | 10 ms | 36 ms | 0 |
| Check 1 | 921 | 21 / 46 / 68 ms | 43 ms | 12 ms | 32 ms | 0 |
| No check 2 | 815 | 18 / 41 / 92 ms | 38 ms | 10 ms | 34 ms | 0 |
| Check 2 | 723 | 19 / 37 / 84 ms | 34 ms | 11 ms | 31 ms | 0 |

- `drain()` changes nothing when every connection is healthy, so these numbers are the cost of the check itself.
- Per call: **+0.7–0.9 ms at p95**, one extra round trip, as before (+0.6–0.8 ms in the first measurement).
- When the pool is the bottleneck, the check costs **41% of throughput** on the cheapest possible query: each
  checkout now waits for two round trips instead of one. Codex measured the same shape (2,144–2,271 → 1,105–1,291).
- In real chat traffic at 1,000 online, the two runs *without* the check differ from each other (p99 47 vs 92 ms) as
  much as they differ from the runs with it. At this load the check is lost in the noise.

## Concepts

### A hung connection (vs a dead one)
- **Simple definition:** a *dead* connection fails at once (the server closed it). A *hung* one is still open, accepts
  what you send, and never answers.
- **Why it's worse:** an error is quick; waiting has no end unless something sets a time limit. psycopg doesn't set
  one on the client side.

### `pool.drain()` vs `pool.check()`
- **`check()`:** takes every idle connection out of the pool, tests each one (one round trip each, one after the
  other), puts the good ones back. Exact, but it runs on the caller's thread and is as slow as the slowest connection.
- **`drain()`:** takes every idle connection out, closes it without asking the server anything, and asks the pool's
  background workers to open replacements. Closing can't hang. Connections in use are replaced when they come back.
- **Small example:** 10 idle connections, 1 hung. `check()`: the caller waits on the hung one forever, the pool is
  empty meanwhile. `drain()`: 10 closes in microseconds, then 10 fresh connections (~7 ms each) from the workers.

### A test proxy
- **Simple definition:** a program in the middle that forwards bytes both ways, and that a test can tell to misbehave.
- **Why:** you can't ask Postgres to "hang one connection". The proxy lets the test choose which one, and works in CI
  where the test can't reach the Postgres container's processes.

## Walkthrough

`root/db.py`:
```python
try:
    ConnectionPool.check_connection(conn)
except Exception:
    from django.db import connections

    connections['default'].pool.drain()
    raise
```
The only change from the first version: `drain()` for `check()`. The `raise` still tells the pool "this one is
dead"; its next try waits for a fresh connection from the workers.

`root/test_database.py`, the proxy's copying loop:
```python
while data := source.recv(65536):
    if client_port in self.hung_ports:
        self.closed.wait()
        return
    target.sendall(data)
```
- Each proxied connection has two of these loops, one per direction. Only the server-to-client one knows the client's
  port, so only answers are held.
- `hang(conn)` finds the port: our end of the psycopg connection's socket (`conn.pgconn.socket`).
- `self.closed.wait()`: the hang lasts until the test ends it (`proxy.close()` in a cleanup), then the connection drops.

The test picks connections by position in the pool's queue (`connection.pool._pool`, a private attribute; fine in a
test, never in app code): the pool hands them out from the left, and `pool.check()` tested from the right, so the hung
one sits at the right end, where the old cleanup met it first.

## Problems
- **One hung connection stalled every request** → [P-44](../problems-and-solutions.md#p-44--one-hung-connection-stalled-every-request-during-the-pools-cleanup).
- **The first failure message was cut off** (`'Operatio[1505 chars]'`). unittest shortens long diffs; setting
  `self.maxDiff = None` for one run showed all 20 timeouts. Named threads (`first`, `crowd-N`) made the output
  readable.

## Decisions
- `drain()` over `check()`: [decision 015](../decisions/015-check-pooled-connections.md#update-codex-review-of-45-how-to-get-rid-of-the-others).

## What I should remember
- A fix that does network work one item at a time on a request's thread is only as fast as the slowest item.
- Dead and hung are different failures; test both.
- Overhead depends on load: +0.8 ms per call is invisible at 1,000 online, and −41% throughput when the pool is the
  bottleneck. Say which one you measured.

## Review questions
1. Why did one hung connection make 20 *other* requests time out with `pool.check()`?
2. Why can't `pool.drain()` hang?
3. What does `drain()` cost compared with `check()` when only one connection was dead?
4. Which request can still wait for a hung connection after this fix, and why isn't that new?
5. Why does the test need a proxy, instead of telling Postgres to hang a connection?
6. The check costs 41% of throughput in one measurement and nothing visible in another. How can both be true?

<details><summary>Answer key</summary>

1. `check()` takes every idle connection out of the pool before testing them one by one. It got stuck on the hung
   one, so the pool stayed empty, and the others waited for a free connection until the 5 s timeout.
2. It never waits for the server: it closes connections (no answer needed) and leaves opening new ones to the pool's
   background workers.
3. It replaces every connection, healthy ones too: up to 10 reconnects of ~7 ms each, in the background. `check()`
   would only have replaced the dead one.
4. One that is handed the hung connection directly by the pool, before any drain: its check waits. Before this PR its
   query would have waited the same way.
5. Postgres has no switch for "hang this connection", and in CI the test can't reach the Postgres container's
   processes. The proxy can hold one connection's answers.
6. The 41% is with 40 threads fighting over 10 connections and a query that costs almost nothing, so the check's extra
   round trip is half the work. At 1,000 chat users the pool is rarely full and each call does more, so +0.8 ms
   disappears in the run-to-run noise.
</details>

## Next steps
- Codex review round 2 of PR #45; the assistant merges after it.
- If the pool becomes the bottleneck under real load: check only connections that sat idle for a while (decision 015,
  option 4).
