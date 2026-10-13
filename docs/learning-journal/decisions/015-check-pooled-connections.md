# 015 · Check each pooled connection; on a dead one, check them all

- **Date:** 2026-10-13 · **Status:** Accepted (Codex review of #38–#43, session 035)

## Problem
The connection pool (T-13, decision 1.2 in the plan) keeps connections open between requests. After Postgres
restarts, all of them are dead, and the pool hands them out anyway: the next requests fail.

## Options considered
1. **No check** (before). Each dead connection fails one request, then gets replaced.
2. **`CONN_HEALTH_CHECKS = True`.** Django then gives the pool psycopg's default check (an empty query on checkout).
   Measured: 3 dead connections cost the next request 2.9 s, 10 made it fail after 5 s (the pool waits longer and
   longer between tries, P-38).
3. **Our own check**: the same empty query, and on a dead connection `pool.check()` drops every dead one at once.
4. **Check only connections idle for a while** (e.g. more than a few seconds). Cheaper, but a connection killed while
   in use (failover, an admin) would still reach one request, and it needs our own bookkeeping.
5. **Retry failed requests** in the app. Only safe for reads, and touches every caller.

## Chosen: 3
- One request after a restart doesn't fail, even with a full pool (~18 ms instead of a 5 s timeout).
- Ten lines in one place; nothing in views or consumers changes.

## Disadvantages and limits
- **One extra round trip on every checkout**: about +0.6–0.8 ms at p95 per database call on this Mac (session 035).
  A message costs several calls, so a few ms per message.
- A connection that dies *during* a request still fails that request. The check only covers connections waiting in
  the pool.
- Uses psycopg_pool's `check()` and Django's `connections['default'].pool`: with a second database alias, the check
  would need to know which pool it belongs to.

## When another option is better
- **4** if the check shows up in profiles (e.g. after PERF-1 is fixed and calls get much cheaper).
- A pooler outside the app (PgBouncer) when there are many processes: it can check server connections itself.
