# 015 · Check each pooled connection; on a dead one, replace them all

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
- Uses psycopg_pool's `drain()` (was `check()`, see the update below) and Django's `connections['default'].pool`:
  with a second database alias, the check would need to know which pool it belongs to.

## Update (Codex review of #45): how to get rid of the others
`pool.check()` tested every idle connection, one after the other, on the thread of the request that found the dead
one, and kept all of them out of the pool meanwhile. One connection that **hung** (the server keeps the connection open
but never answers) stopped that request, and every other request waited for a connection until the 5 s timeout (P-44).
1. **`pool.check()`** (before): finds exactly the dead ones, but runs on the request's thread and can wait forever.
2. **`pool.check()` in a background thread**: the request is free, but the idle connections are still out of the pool
   while it runs, so the others still wait.
3. **A time limit on each test**: psycopg has no per-query timeout on the client side; it would need our own socket
   handling.
4. **`pool.drain()`**: closes every idle connection at once, without testing any, and opens new ones in the pool's
   background workers. Connections in use are replaced when they come back.

**Chosen: 4.** Closing a connection doesn't wait for the server, so nothing can hang, and new connections come from the
pool's own workers. Measured: a pool with 5 dead, 1 hung and 4 healthy connections, then 21 requests: before, one stuck
and 20 timed out; now all 21 succeed, the slowest in 15–27 ms (session 035 follow-up).
- **Price:** on one dead connection, *all* connections are replaced, healthy ones too: up to 10 new connections of
  ~7 ms each, opened in the background. After a restart they're all dead anyway; a lone dead one (an admin killed it)
  costs a few reconnects for nothing.
- **Still open:** a request that is handed the hung connection itself, before any drain, waits as long as the hang
  lasts. That was true before this PR too (its query would hang instead of the check). TCP keepalives catch a dead
  network, but not a server that keeps the connection open and doesn't answer.

## When another option is better
- **4** if the check shows up in profiles (e.g. after PERF-1 is fixed and calls get much cheaper).
- A pooler outside the app (PgBouncer) when there are many processes: it can check server connections itself.
