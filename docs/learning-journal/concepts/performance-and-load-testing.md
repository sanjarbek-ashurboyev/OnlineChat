# Performance and load testing

**Prerequisites:** [HTTP and WebSockets](http-and-websockets.md), [Channels and Redis](django-channels-and-redis.md).

## 1. Simple definition
- **Load testing** means simulating many users to see how the app behaves as the load grows.
- The **bottleneck** is the one resource that runs out first: CPU, a thread, database connections, memory.
- **Scaling** is raising that limit: making each unit of work cheaper, or adding more workers.

## 2. Why it exists
Guessing where the slowness is usually guesses wrong. Measuring shows the actual limit, so you
fix the right thing, and can prove the fix worked.

## 3. How it works: the method used in this project
1. **Model the workload.** What does a typical user do? (Ping every 30 s, reload the chat list
   every 45 s, some of them send N messages a minute.)
2. **Step test.** Add users in steps (50, 100, 250…). Hold each step and record latencies. The step
   where p95 jumps is where the limit is.
3. **Find the mechanism.** Profile, read the library source, measure the parts in isolation.
4. **Fix the cheapest factor**, then measure again.

### Why latency "explodes" suddenly: utilisation
Think of one cashier. At 40% busy, a customer rarely waits. At 90% busy, queues build up faster
than they drain. Waiting time grows roughly like `busy / (1 - busy)`: 0.4/0.6 ≈ 0.7, but
0.9/0.1 = 9, so more than 10× worse. That's why systems look fine and then suddenly don't.

## 4. Small example: the arithmetic from the audit (PERF-4)
- Each database call costs about 6.5 ms: 6.2 ms to connect plus 0.2–0.3 ms for the query.
- One message delivered and read costs about 7 calls.
- 200 users, half of them active, each sending 10 messages a minute: 16.7 messages/s, so about
  117 calls/s from messages, plus pings and polls, about 133 calls/s.
- 133 calls/s × 6.5 ms ≈ 0.86, so the single thread is **86% busy**, and p95 explodes.
- At 100 users it's about 42% busy: healthy. That matches the measurement.

## 5. In our project
- `chats/management/commands/loadtest_seed.py` creates paired fake users and writes their tokens
  to `loadtest/tokens.json` (gitignored, because the tokens are live).
- `loadtest/run.py` uses `aiohttp` to simulate browsers exactly like `app.js`. It reports message,
  ping and chat-list p50/p95/p99 per step, and marks a step failed if p95 or the error rate passes a limit.
- **Measured result:** 100 online users healthy, 200 failing, on one process with a heavy profile,
  with the client on the same Mac.
- **Mechanism** ([audit PERF-1…4](../../scaling/01-audit.md#15-confirmed-findings-performance)):
  1. `database_sync_to_async` sends all of a process's ORM calls to **one thread**.
  2. `CONN_MAX_AGE=0` means a new Postgres connection for every call.
  3. There are about 7 calls per message.
- **Planned fixes, cheapest first:** connection pooling (`psycopg[pool]`, installed in T-08), fewer
  writes per message (don't touch `last_seen` on every ping), a cheaper chat list query, then
  more processes.

## 6. Alternatives
- **Load-testing tools:** Locust (Python, has a UI), k6 (JavaScript), Gatling, Artillery. We wrote
  a small custom script because the behaviour is WebSocket-specific and must match `app.js`.
- **Scaling approaches:**
  - **Vertical:** a bigger server. Simple, but it has a ceiling.
  - **Horizontal:** more servers behind a load balancer. Needs a shared channel layer, which we have
    through Redis, and sticky-free design.
  - **Rewrite** in another framework. Expensive, and doesn't remove the database cost.

## 7. Common mistakes
- **Running the load generator on the same machine as the server.** They compete for CPU, so the
  results come out pessimistic. Our first test did this, and the docs say so.
- **Reporting averages.** An average of 100 ms can hide 5% of users waiting 3 s. Use p95/p99.
- **Testing an unrealistic workload.** Our first profile had about 6× more messages per user than
  a realistic one. The plan's first task is to re-measure with a realistic profile.
- **Optimising before measuring**, or fixing several things at once so you can't tell which helped.

## 8. When to use it
Before launch, before and after any performance change, and before a planned traffic increase.
You don't need it for a feature that touches no hot path.
