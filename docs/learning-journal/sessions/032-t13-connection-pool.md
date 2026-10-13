# 032 · T-13: a connection pool, and one process goes from 500 to 2,000 online

- **Date:** 2026-10-13 · **Phase:** Stage 1 (first efficiency fix)
- **Task:** T-13, psycopg 3 connection pool ([plan Decision 1.2](../../scaling/02-plan.md), audit PERF-2) ·
  **Branch:** `t-13-db-pool`, stacked on `t-21-readyz` (PR #41)
- **Files:** `root/settings.py`, `root/test_database.py` (new), docs
- **Objective:** stop opening a new Postgres connection for every WebSocket database call, and measure what it buys.

## What was done
1. **Measured one call first** (the "micro-benchmark"). A small script repeats, 1,000 times, exactly what channels'
   `database_sync_to_async` does for every socket call: `close_old_connections()`, one small query,
   `close_old_connections()`.
2. **"Before" load test** at `d175abd` (everything up to `/readyz`, no pool).
3. **Test first** (`root/test_database.py`, runs on Postgres only): 20 socket-style calls must use fewer than 5
   different Postgres connections (`pg_backend_pid()`). Without the pool: **20 connections for 20 calls**, a fail.
4. **Code:** one line in `DATABASES['default']`:
   `'OPTIONS': {'pool': {'min_size': 2, 'max_size': 10, 'timeout': 5}}` (the plan's values). The test passed 3/3.
5. **"After" load test** at `ae87ba3`, same steps, then one more run at 1,500 / 1,750 / 2,000 to find the new ceiling.
6. **Results:** `make test` **163 run, OK (16 skipped)**; real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True`
   **198 OK**; Ruff clean; `manage.py check` clean.

### How the load tests were run
- Server: `daphne -b 127.0.0.1 -p 8001 root.asgi:application`, one process, `DJANGO_DEBUG=False`, HTTPS redirect off,
  the secret key from `.env` (the seed signs the tokens with it).
- Before each run: `loadtest_seed --users 2000 --token-hours 4 --force` (2,000 users, 1,000 chats, 20,000 messages).
- Tester: `loadtest/run.py --steps 100,250,500,750,1000,1250 --hold 60 --keep-going`, on the same Mac. Same profile as
  session 028.
- Every 5 s: Daphne's CPU and memory, its open sockets, Postgres client connections, and Postgres's session counter.
- All files (results, server samples, Daphne logs, the scripts) are in `~/onlinechat-runs/2026-10-13/`, outside the
  repo. Daphne was stopped after every run (port 8001 free).

## Results

**One database call, as the socket makes it** (1,000 calls, two runs each)
| | p50 | p95 | p99 |
|---|---:|---:|---:|
| No pool | 6.9 ms | 7.6 ms | 8.9–10.5 ms |
| Pool | **0.45 ms** | **0.67 ms** | 0.9–1.0 ms |

The acceptance was "< 1 ms p95": met.

**Load test** (message echo latency, ms)
| Users | Before p50 | Before p95 | Before p99 | After p50 | After p95 | After p99 | Before | After |
|---:|---:|---:|---:|---:|---:|---:|---|---|
| 100 | 63 | 86 | 101 | 19 | 25 | 28 | OK | OK |
| 250 | 62 | 149 | 222 | 18 | 28 | 37 | OK | OK |
| 500 | 64 | 246 | 667 | 19 | 31 | 37 | OK | OK |
| 750 | 81 | **467** | 728 | 19 | 35 | 52 | **FAIL** | OK |
| 1,000 | 171 | **8,690** | 11,136 | 16 | 33 | 67 | **FAIL** | OK |
| 1,250 | 4,556 | **19,003** | 23,894 | 15 | 32 | 52 | **FAIL** (73 lost) | OK |
| 1,500 | | | | 15 | 32 | 79 | | OK |
| 1,750 | | | | 15 | 45 | 166 | | OK |
| 2,000 | | | | 17 | **86** | **374** | | OK |

No step had connect errors, drops, poll errors or `server_errors`. The chat list p95 stayed under 70 ms.

**Server**
| | Before (no pool) | After (pool) |
|---|---|---|
| New Postgres sessions during the 6-step run (the sampler's own `psql` adds 154 before, 146 after) | **33,566** | **227** |
| Daphne CPU at 1,250 sockets, avg (max), % of one core | 60% (63%) | 26% (37%) |
| Daphne CPU at 2,000 sockets | | 38% (56%) |
| Postgres client connections, max | 4 | 11 (= the pool's 10 + the sampler's own `psql`) |
| Memory at 1,250 / 2,000 sockets | 168 MB / | 166 / 209 MB |

## What the numbers say
1. **One process: healthy at 500 before, at 2,000 (at least) after.** 2,000 is every seeded user, so the real ceiling
   is higher and still unknown. This already meets the to-do goal ("healthy at 1,000+").
2. **The cause was the connection, as the audit predicted** (*Confirmed* now, by changing only that): 33,566 → 227
   new sessions, and 6.9 ms → 0.45 ms per call. The socket thread spent most of its time waiting for Postgres to
   start a new process.
3. **Even small loads got faster** (100 users: p95 86 → 25 ms). Every message waited for several connects, even
   with no queue.
4. **The slope is back at 2,000:** p99 went 52 → 79 → 166 → 374 ms from 1,250 to 2,000. That's the start of the
   next queue, still far from the 1 s limit.
5. **The pool was full** (10 connections) from about 1,000 sockets on, with no waits long enough to time out
   (no `PoolTimeout` in the logs). Something holds connections for longer than the socket thread does (likely the
   REST chat-list polls); worth a look before raising `max_size` or adding processes.

## Problems and observations
- **289 `group_discard failed` errors (`MaxConnectionsError`) at the end of the 2,000 run**, all within 2 seconds
  (16:33:35–36), when the tester closed 2,000 sockets at once. That's the known channels-redis pool limit
  ([P-13](../problems-and-solutions.md#p-13--a-burst-of-disconnects-left-users-online-cor-2)), and the "Redis pool sizing" item in
  the to-do. T-02's fix held: the users were still marked offline. None at 1,250 or below.
- **The full real-stack suite took ~200 s instead of ~121 s earlier in the day.** Checked: without the pool it took
  205.9 s too, and the slowest tests (the chat-list browser tests, ~11 s each, which create 50+ users with the real
  password hasher) take 80.5 s with or without it. So it's this machine after three load tests, not the pool.

## Concepts

### Connection pool
- **Simple definition:** a small set of open database connections that the app borrows and gives back, instead of
  opening a new one each time.
- **Why it matters here:** opening a Postgres connection means a TCP handshake, a password check (SCRAM) and a new
  server process: ~6.9 ms. The query itself took well under 1 ms. Channels closes the connection after every socket
  call, so without a pool every call paid the 6.9 ms.
- **How Django does it:** with `OPTIONS['pool']`, `connection.close()` hands the connection back to the pool instead
  of closing it. Nothing else in our code changed.
- **Its three numbers:** `min_size` (kept open even when idle), `max_size` (never more than this per process), and
  `timeout` (how long to wait for a free one before failing).
- See also the [performance guide](../concepts/performance-and-load-testing.md).

### Little's law (sizing the pool)
Connections busy on average = calls per second × seconds each is held. At 1,000 calls/s × 0.5 ms that's 0.5
connections. `max_size` exists for bursts and slow queries. Across all processes, the total must stay under
Postgres's `max_connections` (100 here) minus a reserve for admin and migrations.

## Walkthrough
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        ...
        'OPTIONS': {'pool': {'min_size': 2, 'max_size': 10, 'timeout': 5}},
    }
}
```
- Requires psycopg 3 and `psycopg-pool` (both pinned since T-08) and Django ≥ 5.1 (we run 6.1.2).
- `CONN_MAX_AGE` must stay 0 (the default); Django refuses persistent connections together with a pool.
- `root/settings_test.py` replaces `DATABASES` with SQLite, so the SQLite test run is unaffected.

```python
pids = {async_to_sync(database_sync_to_async(backend_pid))() for _ in range(20)}
self.assertLess(len(pids), 5, f'{len(pids)} different connections for 20 calls')
```
- `pg_backend_pid()` is the id of the Postgres process serving this connection. A new connection = a new pid.
- My first version asserted "≤ 2" (the pool's `min_size`) and failed with 3: the test's own connection comes from
  the pool too. The exact number is the pool's business; the point is "a few, not one per call".

## Decisions
- The plan's values (2 / 10 / 5 s) as they are. The load test didn't show a reason to change them yet.
- No new decision record: [plan Decision 1.2](../../scaling/02-plan.md) already chose the built-in pool over
  `CONN_MAX_AGE` and PgBouncer. Its "Result" line now has the numbers.

## What I should remember
- One process: **500 healthy before the pool, 2,000+ after.** Same test, same machine, same day.
- Measure the smallest thing first (one call: 6.9 → 0.45 ms), then the whole system. The micro-benchmark explains
  the load test.
- Change one thing between "before" and "after", and run both within the same hour.
- A slower test suite after a change isn't proof the change did it: run it without the change, in the same
  conditions.

## Review questions
1. Why did every socket call open a new connection before T-13, even though our code never asks for one?
2. 33,566 new Postgres sessions in one run before, 227 after. Where did the 227 come from?
3. Why did the 100-user step get faster too, when nothing was queueing there?
4. The pool's `max_size` is 10, and we saw 11 client connections. Why?
5. The full suite took 200 s with the pool. What did we run to decide the pool wasn't the cause?
6. Using Little's law: at 2,000 calls/s and 0.5 ms per call, how many connections are busy on average?

<details><summary>Answer key</summary>

1. Channels' `database_sync_to_async` calls `close_old_connections()` before and after every call, and with
   `CONN_MAX_AGE = 0` that closes the connection. The next call opens a new one.
2. **146 of them were the measurement itself:** the sampler ran 2 `psql` queries per sample, 73 samples, each a new
   session (counted). The other ~81 are the app (*hypothesis:* the pool opening and replacing its connections, and
   REST requests). Either way: about 81 over 9 minutes instead of one per call.
3. Each message makes several database calls, and each used to pay ~6.9 ms to connect. That cost was there even
   without a queue: 7 calls × 6.9 ms ≈ 48 ms per message.
4. The sampler counts client connections with `psql`, and that `psql` is a client connection too.
5. The same full suite without the pool, right after: 205.9 s. And the slowest 7 tests: 80.5 s with and without.
6. 2,000 × 0.0005 s = 1 connection on average. The rest of `max_size` is for bursts and slower calls.
</details>

## Next steps
- T-15 (`touch_last_seen` at most once per 60 s per socket) and T-16 (async presence), re-running this test after each.
- Find the real ceiling: seed more than 2,000 users and step past 2,000.
- channels-redis pool sizing (the 289 `MaxConnectionsError`s at the end of the 2,000 run).
- Check what holds pool connections at ~1,000 sockets before adding processes (T-22).
