# Connection pools

## 1. Simple definition
A **connection pool** is a small set of open database connections that the app borrows for one piece of work and
gives back, instead of opening a new connection each time. "Checkout" = borrowing one; "return" = giving it back.

## 2. Why it exists
Opening a Postgres connection is slow compared with a small query: a TCP handshake, a password check and a new
server process. Here that was ~6.9 ms against well under 1 ms for the query itself (session 032). A pool pays the
opening cost once and reuses the connection thousands of times.

## 3. How it works, step by step
1. At start the pool opens `min_size` connections.
2. A request asks for one. A free one → it gets it. None free and fewer than `max_size` open → the pool opens another.
   Otherwise the request waits, at most `timeout` seconds, then fails.
3. The request runs its queries and gives the connection back. It stays open for the next request.
4. Connections idle for a long time are closed again, down to `min_size`.
5. **Optionally, on checkout, the pool tests the connection** (an empty query). Dead → it throws it away and tries
   another.

## 4. Small example
```
request 1: checkout A → SELECT … → return A
request 2: checkout A → SELECT … → return A      (no new connection: ~0.5 ms instead of ~7 ms)
Postgres restarts → A is dead, but still in the pool
request 3: checkout A → without a check: error. With a check: A fails the test, the pool opens B → SELECT … works
```

## 5. In our project
- `root/settings.py`: `OPTIONS['pool']` = `min_size 2`, `max_size 10`, `timeout 5`, per process (T-13, session 032).
  Django's `connection.close()` returns the connection to the pool instead of closing it.
- `check`: `root/db.py` `check_pooled_connection` tests every checkout, and when it finds one dead connection it
  tests all idle ones at once (`pool.check()`). Without that, a pool of 10 dead connections made a request wait past
  the 5 s timeout ([decision 015](../decisions/015-check-pooled-connections.md), session 035).
- Cost of the check: about +0.6–0.8 ms at p95 per database call on this Mac.

## 6. Alternatives
- **Persistent connections** (`CONN_MAX_AGE > 0`): one connection per thread, kept between requests. Django doesn't
  allow it together with the pool. With Channels, `database_sync_to_async` closes the connection after each call, so
  it would help less.
- **An external pooler** (PgBouncer) between the app and Postgres. Many app processes then share a few server
  connections. Useful when processes × `max_size` gets close to Postgres's `max_connections`.
- **No pool**: simplest, and fine for a low-traffic site.

## 7. Common mistakes
- **No check, and a database restart.** Every connection opened before the restart is dead; each one fails a request.
- **Testing only the easy case.** A check that recovers from 3 dead connections can still time out with a full pool
  (P-38).
- **Too large a pool**: processes × `max_size` above Postgres's `max_connections` → "too many clients" errors.
- **Tests sharing a pool**: one test fills it, and the next test's assumptions about "fresh" connections break.
  `connection.close_pool()` gives the next test a new one.

## 8. When to use it
As soon as connecting costs a noticeable part of a request, as it did here. Add the checkout check whenever the
database can restart or fail over while the app keeps running, which in production is always.
