# 034 · T-15: `last_seen` once a minute per socket, not on every frame

- **Date:** 2026-10-13 · **Phase:** Stage 1
- **Task:** T-15 ([backlog](../../scaling/03-operations.md), audit PERF-3) · **Branch:** `t-15-last-seen-interval`
- **Files:** `chats/consumers.py`, `chats/test_consumers.py`, docs
- **Objective:** stop writing to Postgres on every ping and message just to record "last seen".

## What was done
1. **Read the code.** `InboxConsumer.receive()` called `touch_last_seen()` (an `UPDATE` of the user row) for every
   frame: each ping (one per user every 30 s), each message, each read receipt. REST already limits the same write to
   once a minute (`accounts/authentication.py`, `TOUCH_INTERVAL`).
2. **"Before" load test** on `main` at `fba1bbc` (after the Redis pool fix), 3,000 users seeded, steps up to 3,000.
   New: the sampler also records Postgres's own counters (`pg_stat_database.xact_commit` and `tup_updated`), the
   "query counter" the backlog's acceptance asks for.
3. **Tests first** (`LastSeenTests`, 3 tests): frames within the interval don't write `last_seen`; a frame after it
   does; connect and disconnect always do. On the old consumer: **1 failure** (pings and a message overwrote a
   one-hour-old `last_seen`) and **1 error** (`LAST_SEEN_INTERVAL` didn't exist). The connect/disconnect test is a
   guard (it passed already).
4. **Code:** `LAST_SEEN_INTERVAL = 60`. `touch_last_seen()` remembers when it last wrote (`self.last_seen_at`,
   `time.monotonic()`); `receive()` only calls it when 60 s have passed. Connect and disconnect are unchanged.
5. **"After" load test** at `77a9bf6`, same steps and seed size.
6. **Results:** all 34 consumer tests pass; `make test` **167 run, OK (17 skipped)**; real Postgres + Redis with
   `REQUIRE_BROWSER_TESTS=True` **202 OK**; Ruff clean.

**Not done:** the planned extra "before" and "after" runs, interleaved, to measure the run-to-run spread of the
ceiling (stopped by Alex's change of plan). So the ceiling comparison below is one run each.

## Results

**Postgres's own counters, whole run** (same steps 100 … 3,000; about 11,750 messages sent in each)
| | Before | After | Change |
|---|---:|---:|---:|
| Rows updated | 52,984 | **23,728** | −55% |
| Transactions (≈ database calls) | 199,819 | **169,057** | −15% |
| Per message sent: rows updated | 4.5 | **2.0** | −2.5 |
| Per message sent: transactions | 16.9 | **14.4** | −2.5 |

"Per message" divides everything in the run (pings, polls, receipts too) by the messages sent, so it's a ratio for
comparing two runs, not the cost of one message. The backlog's acceptance was "DB calls per message drop by 2": the
measured drop is **2.5**.

**Load test** (message echo, ms; one Daphne process)
| Users | Before p95 | Before p99 | After p95 | After p99 | Before | After |
|---:|---:|---:|---:|---:|---|---|
| 500 | 31 | 41 | 25 | 34 | OK | OK |
| 1,000 | 31 | 46 | 30 | 70 | OK | OK |
| 1,500 | 48 | 236 | 43 | 170 | OK | OK |
| 1,750 | **416** | 869 | 49 | 199 | **FAIL** | OK |
| 2,000 | **1,457** | 2,402 | 60 | 281 | **FAIL** (12 lost) | OK |
| 2,500 | 24,319 | 31,301 | **391** | 706 | FAIL (434 lost) | FAIL |
| 3,000 | 58,901 (500 not connected) | 61,879 | **696** | 1,015 | FAIL (1,498 lost) | FAIL (12 lost) |

No errors in either Daphne log.

## What the numbers say
1. **The writes went down by more than half**, as designed: most `UPDATE`s were `last_seen` from pings.
2. **The ceiling comparison is weaker than it looks.** This "before" run failed at 1,750, but the same code
   (session 033's "after" run, `54831d1` + docs) was healthy at 2,000 an hour earlier, and so was the run before it.
   So "before 1,500 → after 2,000" is partly noise. Over the three 3,000-user runs of pre-T-15 code: healthy to
   **1,500–2,000 before, 2,000 after** (one run); failing at 2,500 either way. *Not* a demonstrated ceiling gain.
3. **Past the ceiling, it degrades much more gently.** At 3,000 the after-run lost 12 messages with p95 0.7 s; the
   three earlier runs at 3,000 (before code) lost 40, 262 and 1,498 with p95 3–59 s. Fewer calls on the one database
   thread means its queue grows more slowly once it's overloaded. (*Hypothesis*, consistent with every run so far.)
4. **Low load got slightly faster** (500 users: p95 31 → 25 ms): one database call less per ping and message.

## Problems
- **Run-to-run spread near the ceiling** ([P-37](../problems-and-solutions.md#p-37--the-same-code-was-healthy-at-2000-in-one-run-and-failed-at-1750-in-the-next)):
  the same code was healthy at 2,000 in one run and failed at 1,750 in the next. Database bloat ruled out (autovacuum
  current, 642 dead rows at most). Cause not found: *hypothesis* is the Mac itself (the tester shares it, plus
  whatever else runs). Lesson: compare counters, and interleave runs before claiming a ceiling moved.

## Concepts

### Throttling a write (debouncing)
- **Simple definition:** do something at most once per interval, however often you're asked.
- **Here:** a ping every 30 s asked for a `last_seen` write every 30 s. "Online" already comes from presence (Redis);
  `last_seen` only matters once you're *offline*, and disconnect writes the exact time then. So a once-a-minute value
  while online loses nothing anyone sees.
- **Example:** a socket open for 10 minutes with pings every 30 s: 20 writes before, 1 + 10 + 1 = 12 at most after
  (connect, one a minute if frames keep coming, disconnect), and only 2 if it's quiet.

### Measuring at the source
Postgres counts committed transactions and updated rows itself (`pg_stat_database`). Reading those counters before and
after a run gives "database work per message" without instrumenting the app, and it isn't affected by how fast the
server happened to be that run.

## Walkthrough: `chats/consumers.py`
```python
LAST_SEEN_INTERVAL = 60

        if time.monotonic() - self.last_seen_at >= LAST_SEEN_INTERVAL:
            await self.touch_last_seen()

    @database_sync_to_async
    def touch_last_seen(self):
        self.last_seen_at = time.monotonic()
        User.objects.filter(pk=self.user.pk).update(last_seen=timezone.now())
```
- `time.monotonic()`, not `time.time()`: it never jumps back (e.g. when the clock is corrected), so intervals are safe.
- `connect()` calls `touch_last_seen()` before any frame can arrive. Channels handles one event of a consumer at a time,
  so `self.last_seen_at` always exists when `receive()` reads it. Refused sockets return before reaching it.
- The constant is per module so a test can set it to 0 (`mock.patch.object(consumers, 'LAST_SEEN_INTERVAL', 0)`)
  instead of freezing the clock. Patching `time.monotonic` would also freeze asyncio's own clock.

## Decisions
- 60 s, the same as REST, so both doors write `last_seen` at the same rate.
- Connect and disconnect keep writing every time: they're rare, and disconnect is the value people actually see.

## What I should remember
- Look for writes that run on every event but only need to run "now and then".
- Count the work (Postgres counters) when the latency results are noisy.
- Near the ceiling one run proves little: the same code went 1,500 → 2,000 between runs.

## Review questions
1. Why is it safe for `last_seen` to be up to a minute old while the user is online?
2. Why did the rows updated fall by half, but transactions only by 15%?
3. Why can't this session claim "the ceiling went from 1,500 to 2,000"?
4. Why does the test patch `LAST_SEEN_INTERVAL` instead of the clock?
5. Which writes of `last_seen` are left, and when do they happen?

<details><summary>Answer key</summary>

1. While online, the app shows "online" from presence (Redis), not `last_seen`. `last_seen` is shown only once the
   user is offline, and disconnect writes the exact time then.
2. Most `UPDATE`s were `last_seen`, but transactions also include all the reads: loading the chat, checking blocks,
   saving the message, the chat list polls, read receipts. Only one call per frame disappeared.
3. The same code was healthy at 2,000 in another run an hour earlier (and the stock-pool version in a third). One "before" run that happened to fail at
   1,750 isn't enough; the difference is within the spread we've seen.
4. Patching `time.monotonic` changes it for the whole process, including asyncio's event loop, which uses it for
   timeouts. A module constant affects only our check.
5. On connect, on disconnect, and from a frame at most once every 60 s per socket. REST requests still write it at most
   once a minute too (`LastSeenJWTAuthentication`).
</details>

## Next steps
- T-16: async presence (`redis.asyncio`), so presence calls don't queue on the one thread.
- Before claiming a ceiling change again: interleave before/after runs (A-B-A-B), or run each twice.
