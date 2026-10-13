# 033 · The channel layer waits for a Redis connection instead of failing

- **Date:** 2026-10-13 · **Phase:** Stage 1
- **Task:** Redis pool sizing for channels-redis (the T-02 follow-up; to-do section 2) · **Branch:** `t-02-redis-pool-wait`
- **Files:** `chats/layers.py` (new), `root/settings.py`, `chats/test_channel_layer.py`, docs
- **Objective:** a burst of disconnects (or sends) never fails just because the per-process Redis pool is busy.

## What was done
1. **Read the libraries.** channels-redis (4.3.0) builds redis-py's `ConnectionPool` for each event loop. That pool
   (redis-py 8.1.0) holds at most 100 connections and **raises** `MaxConnectionsError` when all are busy.
   `RedisChannelLayer.create_pool()` is a method, so a subclass can choose another pool.
2. **"Before" load test** on `main` (`bd9b2b8`), now with **3,000 seeded users** so the ceiling shows (to-do: "seed
   more users"). Steps up to 3,000.
3. **Test first** (`chats/test_channel_layer.py`, real Redis only): 300 `group_add`s at once, then 300
   `group_discard`s. With the stock pool: `MaxConnectionsError: Too many connections`.
4. **Code:** `chats/layers.py` `WaitingRedisChannelLayer.create_pool()` returns redis-py's `BlockingConnectionPool`:
   the same 100 connections, but a call waits (up to `timeout` = 5 s) for a free one. Settings point the backend at
   it. The test passed 3/3.
5. **"After" load test** at `54831d1`, same steps and seed.
6. **Burst check** (T-02's old acceptance, never run until now): 3,000 sockets connect, all close at once, then count
   what cleanup left in Redis (presence keys with a member; group entries added during the check).
7. **Results:** `make test` **164 run, OK (17 skipped)**; real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True`
   **199 OK**; Ruff clean.

**Not done:** the overloaded 3,000 step wasn't repeated to measure its run-to-run spread (see below).

## Results

**Load test, one Daphne process, 3,000 users seeded** (message echo, ms)
| Users | Before p95 | Before p99 | After p95 | After p99 | Before | After |
|---:|---:|---:|---:|---:|---|---|
| 1,000 | 40 | 78 | 41 | 103 | OK | OK |
| 1,500 | 41 | 163 | 65 | 785 | OK | OK |
| 2,000 | 182 | 464 | 116 | 439 | OK | OK |
| 2,500 | **403** | 672 | **528** | 934 | FAIL | FAIL |
| 3,000 | **3,109** | 4,461 | **10,235** | 14,077 | FAIL (40 lost) | FAIL (262 lost) |

**Errors in Daphne's log**
| | Before | After |
|---|---:|---:|
| `group_discard failed` (`MaxConnectionsError`) | **1,214**, all within 2 s at the end | **0** |

**Burst check: 3,000 sockets close at once**
| | Stock pool | Waiting pool |
|---|---:|---:|
| Errors | 2,881 | 0 |
| Presence keys still "online" after the wait | 0 | 0 |
| Dead entries left in Redis groups | **2,881** (expire after 24 h) | **0** |
| Time until everything was cleaned up | (never, for the groups) | about 3 s |

## What the numbers say
1. **The errors are gone, and so are the leftovers.** With the stock pool, T-02's fix kept presence right, but each
   failed `group_discard` left a dead channel in that user's group for 24 h. Every message to that user was then
   copied into a queue nobody reads.
2. **Capacity didn't change, as expected.** One process: healthy at 2,000, failing at 2,500, before and after. The
   pool only mattered in the final burst. During the steps it never filled: the "before" log has no pool errors
   until the last 2 seconds.
3. **The 3,000 step looks worse after, but it's overloaded in both runs** (*hypothesis*, not measured: run-to-run
   noise). A waiting pool behaves exactly like the old one while it isn't full, and it wasn't. A queue past its
   limit is very sensitive: the "after" run also sent 14% more messages in that step (2,518 vs 2,215).
4. **The real ceiling of one process is now known: between 2,000 and 2,500 online.** The next fixes (T-15, T-16)
   take work off that one thread.

## Problems
- [P-36](../problems-and-solutions.md#p-36--thousands-of-leftovers-in-redis-that-the-app-never-left): after the
  "after" run Redis seemed full of leftovers (2,990 presence keys). My script had stopped Daphne the moment the tester
  exited, mid-cleanup. With a 30 s pause: 0. The script now waits.
- A safety hook stopped one command (it temporarily swapped `root/settings.py` back to `main`'s version for the
  comparison) until I listed what it changes and how to undo it. Fair: that's a file other runs depend on.

## Concepts

### Fail fast vs wait (bounded)
- **Fail fast:** no free connection → error now. Good when waiting can't help (the server is down).
- **Wait, with a limit:** no free connection → wait until one is handed back, up to `timeout`. Good for short
  **bursts**: each `group_discard` holds a connection only briefly, so the queue drains; here all of a 3,000-socket
  cleanup was done in about 3 s.
- Both keep the number of connections bounded (100), which protects Redis. The difference is only what happens to
  call 101.

### Dead group members
A Redis group (here, one per user) is a list of channel names. `group_send` copies the message into each one's queue.
If a socket closes without `group_discard`, its name stays in the group until `group_expiry` (24 h), and gets copies
nobody reads. Harmless for correctness, but wasted work that grows with every burst.

## Walkthrough: `chats/layers.py`
```python
class WaitingRedisChannelLayer(RedisChannelLayer):
    def create_pool(self, index):
        host = dict(self.hosts[index])
        return BlockingConnectionPool.from_url(host.pop('address'), **host)
```
- channels-redis calls `create_pool(index)` once per Redis host and event loop. The stock version calls
  `ConnectionPool.from_url(...)`; we only change the class.
- `dict(...)` copies the host settings, so `pop` doesn't change the layer's own config.
- The rest of the host dict becomes pool and connection options:
  `{'socket_timeout': 10, 'max_connections': 100, 'timeout': 5}` in `root/settings.py`.

## What I should remember
- "Too many connections" was the **client's** pool (100 per process), not Redis (10,000). Read the library first.
- A pool can fail fast or wait; for bursts, wait with a limit.
- Check what a test left behind only after the server has finished; and stopping a server mid-burst skips cleanup.

## Review questions
1. Why did T-02's fix keep presence correct, yet 2,881 entries stayed in the Redis groups?
2. What does call number 101 do with each pool?
3. Why didn't the waiting pool change the load test's ceiling?
4. Why can't the 3,000-user difference (3.1 s vs 10.2 s) be blamed on the new pool?
5. After the first "after" run, Redis held 2,990 presence keys. What was wrong, and how was it proven?

<details><summary>Answer key</summary>

1. T-02 made `disconnect()` catch the `group_discard` failure and still run `mark_offline`. Presence was fixed, but the
   failed `group_discard` itself never happened, so the dead channel stayed in the group until it expired (24 h).
2. Stock `ConnectionPool`: raises `MaxConnectionsError` at once. `BlockingConnectionPool`: waits for one of the 100 to
   be handed back, up to 5 s, then raises.
3. The pool only filled up in the end-of-test burst. During the steps it never had 100 calls at once, and a waiting
   pool that isn't full behaves exactly like the old one.
4. The "before" log had no pool errors during the steps, so the pool was never full there; a waiting pool changes
   nothing until it's full. Both runs were past the limit, where results vary a lot (and "after" sent 14% more).
5. My script stopped Daphne the moment the tester exited, while it was still running 3,000 disconnects. The same
   burst with a pause before stopping left 0, and polling every second showed it was clean within about 3 s.
</details>

## Next steps
- T-15: `touch_last_seen` at most once per 60 s per socket.
- T-16: async presence (`redis.asyncio`), so presence calls don't queue on the one thread.
- T-27 (later): graceful shutdown, so a deploy doesn't cut a cleanup burst short.
