# 028 · Stage 0 baseline, rerun with the fixed tester: healthy at 500, failing at 750

- **Date:** 2026-10-13 (run on 2026-10-12) · **Phase:** Stage 0 (closing) → Stage 1
- **Task:** record the baseline load test (plan §2.4, README step 6, Stage 0 checklist) · **Branch:** `t-12-stage0-baseline` (docs only)
- **Code under test:** `main` at `77722d8` (all 31 Codex findings fixed, PRs #34–#37 merged)
- **Objective:** replace session 014's unconfirmed numbers with a run of the fixed tester (session 017) and the plan's
  limits, so Stage 1 has a starting point to beat.

## What was done
- Ran the step load test from the server Mac itself (no network in between, see [P-19](../problems-and-solutions.md#p-19--the-second-machine-baseline-measured-the-hotspot-not-the-server)),
  against one Daphne process on port 8001. Results saved with `--json` to `loadtest/results-baseline-local.json`
  (gitignored, like every `loadtest/results*.json`).
- Recorded the result in the [Stage 0 checklist](../../scaling/03-operations.md#stage-0-done-ready-for-real-users), the
  [claims tracker](../../scaling/04-interview-guide.md), the [performance guide](../concepts/performance-and-load-testing.md)
  and P-19. The second-machine (VPS) run was dropped, so this server-only number is the Stage 0 baseline.
- Housekeeping: there were two session notes numbered 026. The replay/recovery one is now
  [027](027-session-replay-and-recovery.md), and its links point there.

**What is NOT done / not recorded:**
- The server-side samples (Daphne CPU and memory, Postgres connections) lived in `/tmp` and were gone by the time
  this note was written. So there's no CPU table this time, unlike session 014.
- The JSON file stores the tester's arguments, not the server's settings. The run copied session 014's setup
  (one Daphne process, `DJANGO_DEBUG=False`), but that isn't in the file. From now on, write the server command
  and commit next to the result.
- No second-machine number, no soak test, no reconnect storm.

## Setup
| What | Value |
|---|---|
| Server | This Mac (Apple M4). One Daphne process on `:8001` |
| Generator | `loadtest/run.py` on the same Mac |
| Steps | 100, 250, 500, 750, 1,000, 1,250 users, each held 60 s, connecting 50/s, `--keep-going` |
| Profile | Realistic: 20% of users active at 4 messages/min, a ping every 30 s, the chat list every 45 s |
| Pass rule (the plan's) | Message p95 ≤ 300 ms and p99 ≤ 1 s, chat list p95 ≤ 300 ms, errors < 0.1%, nothing lost |

## Results
| Users | Sent | msg p50 | msg p95 | msg p99 | delivery p95 | ping p95 | list p95 | Lost | Result |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 100 | 82 | 69 | 85 | 111 | 81 | 44 | 43 | 0 | OK |
| 250 | 233 | 71 | 124 | 175 | 124 | 60 | 44 | 0 | OK |
| 500 | 412 | 73 | 267 | 597 | 267 | 96 | 39 | 0 | OK |
| 750 | 633 | 123 | **2,345** | 3,843 | 2,256 | 1,084 | 38 | 0 | **FAIL** |
| 1,000 | 798 | 300 | **12,191** | 15,678 | 10,451 | 3,579 | 38 | 0 | **FAIL** |
| 1,250 | 926 | 4,359 | **25,373** | 31,784 | 24,094 | 7,705 | 49 | **242** | **FAIL** |

All times in ms. Every step connected all its users, with 0 connect errors, 0 drops, 0 poll errors and 0
`server_errors`. At 1,250, 242 of 926 messages got no echo and 221 never reached their recipient.

## What the numbers say
1. **One process is healthy at 500 online and fails at 750.** The 500 step is already close to the line: p95 267 ms
   against a 300 ms limit, and p99 597 ms.
2. **Same shape as session 014: a cliff on the WebSocket path, REST untouched.** The chat list stayed under 50 ms at
   every step, while even pings (the lightest frame) waited over a second at 750. That still points at the single
   thread that runs every WebSocket database call (PERF-1), not at Postgres.
3. **Lower than session 014's "healthy at 750"** (*Hypothesis*, not measured). Three things changed at once: the
   tester (drain at the end of a step, stricter limits), the profile of one run (this one climbs from 100 in one
   go; 014's run 3 started at 500), and the code: each message now does more work (receipts with `up_to`, rights
   re-checks, catch-up on connect). We can't tell how much each one contributed. It doesn't matter for Stage 1:
   this number is the one to beat, measured the same way the "after" runs will be.
4. **At 1,250, messages are lost, not just slow.** The tester waits `--message-timeout` (10 s) for echoes before it
   gives up. With a p50 of 4.4 s, a quarter of the messages missed that window. The message may well be saved in
   Postgres; "no echo in time" is what a user sees as a stuck message.

## Concepts I learned

### Baseline
- **Simple definition:** the measurement you take *before* changing anything, so you can prove a change helped.
- **Why it has to be re-taken:** a baseline belongs to one version of the code and one way of measuring. Session
  014's number came from an older tester, so it can't be compared with Stage 1's results. This one can.
- **Small example:** "pooling made it faster" means nothing. "Healthy at 500 before pooling, at X after, same test,
  same machine" is evidence.

### Utilisation and the cliff (again)
A queue's waiting time grows like 1 / (1 − utilisation). Between 500 and 750 users the one WebSocket thread went
from "busy most of the time" to "never idle", so p95 jumped 9×, not 1.5×. See
[the performance guide](../concepts/performance-and-load-testing.md).

## Walkthrough: reading one step of the JSON
```json
{ "users": 750, "message_p95_ms": 2344.9, "delivery_p95_ms": 2256.5,
  "ping_p95_ms": 1084.5, "poll_p95_ms": 38.5, "lost_messages": 0, "server_errors": 0,
  "problems": ["message p95 2345ms > 300ms", "message p99 3843ms > 1000ms", "delivery p95 2256ms > 300ms"],
  "healthy": false }
```
- `message_p95_ms`: 95% of echoes came back to the sender within this time. This is the plan's SLO.
- `delivery_p95_ms`: the same, measured at the *recipient*. It's what a user actually feels.
- `ping_p95_ms` high while `poll_p95_ms` (REST chat list) is low: the WebSocket side is queueing, REST isn't.
- `problems`: the list of broken limits, written by `loadtest/verdict.py`. Empty list = healthy.
- `server_errors`: error frames the server sent. 0 here. The verdict doesn't count them yet
  ([GOTCHA](../../../GOTCHA.md#load-testing)), so always read that column yourself.

## Problems
- **Server samples lost from `/tmp`.** Not a bug, a process mistake: scratch files aren't a record. Next time, save
  the sampler's CSV next to the JSON, under `loadtest/` (gitignored), and summarise it in the note the same day.

## Decisions
- **Server-only baseline counts for Stage 0.** The second-machine/VPS run was dropped (the owner's call, 2026-10-12).
  Session 014 showed a same-machine generator makes the server look *worse*, not better (it steals CPU), so the
  number is on the safe side.

## What I should remember
- One Daphne process: **healthy at 500 online, failing at 750** (realistic profile, plan limits, `77722d8`).
- REST fine plus WebSocket collapsing = the single WebSocket database thread. Stage 1's first fixes target it.
- Record the server command, the commit and the server samples with every result file.

## Review questions
1. Why couldn't session 014's "healthy at 750" be the Stage 0 baseline?
2. At 750 users, ping p95 was 1,084 ms but the chat list p95 was 38 ms. What does that tell you?
3. At 1,250 users no connection dropped, yet 242 messages were "lost". What does "lost" mean in this tester?
4. Why is a same-machine generator a *pessimistic* setup for the server?
5. The 500 step passed with p95 267 ms. Would you call 500 users "safe" for production? Why or why not?

<details><summary>Answer key</summary>

1. It came from the old tester, which had bugs (P-23) and looser limits (500 ms, 1%). A baseline must be measured
   the same way as the "after" runs, or the comparison means nothing.
2. Pings and messages go through the WebSocket consumer, whose database calls share one thread per process; the
   chat list is a REST request with its own thread. Only the shared path is queueing.
3. The tester waited 10 s for the echo after sending stopped and never got it. The message may be saved in
   Postgres, but the sender's socket didn't confirm it in time, which a user sees as a stuck message.
4. The generator and the server compete for the same CPU, so the server gets less than a whole machine. With the
   generator elsewhere, the server can only do as well or better (if the network is good).
5. No. It's 89% of the p95 limit and p99 is already 597 ms. One busier minute (more active users, a reconnect
   burst) would push it over. You want headroom, which is what Stage 1 is for.
</details>

## Next steps
- T-13 (connection pool) first, with a fresh before/after run of this exact test.
- Then T-15 (fewer `last_seen` writes) and T-16 (async presence), re-running the test after each.
- Teach the load-test verdict to count `server_errors` (open item from session 027).
