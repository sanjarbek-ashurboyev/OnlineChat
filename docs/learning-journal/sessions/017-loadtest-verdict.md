# 017 · Codex review: a load tester that can say FAIL

- **Date:** 2026-10-11 · **Phase:** Stage 0
- **Task:** finding #8 from the Codex review (session 015), not in the backlog · **Branch:** `fix-loadtest-verdict`
- **Files:** `loadtest/run.py`, `loadtest/verdict.py` (new), `loadtest/test_verdict.py` (new), `loadtest/__init__.py` (new), docs
- **Objective:** the tester reports FAIL whenever messages go missing or aren't measured, judges against the plan's
  targets, and counts online users correctly across steps.

## Before we started
- PR #26 (findings #3–#6) merged as `73c42da`. Branched `fix-loadtest-verdict` from the updated `main`.

## What we accomplished
1. **Reproduced the bug with the real tester first.** I seeded 40 load-test users locally, blocked every pair
   (so the server rejects every message), started Daphne, and ran the **old** `run.py`:
   `40 users, 194 sent, msg95 "-"` → **OK**. Nothing arrived, and the tester called it healthy.
2. **Moved the pass/fail rules** into `loadtest/verdict.py`, which doesn't import `aiohttp`, so the normal test suite
   can run its 6 unit tests (`loadtest/test_verdict.py`).
3. **Fixed `run.py`:**
   - each step ends with a **drain**: sending pauses, the tester waits up to `--message-timeout` (10 s) for messages
     in flight, and whatever is still missing is **lost**;
   - messages sent during the ramp are forgotten together with the ramp's counters;
   - online users are counted from each socket's own `closed` flag, not "connected minus this step's drops";
   - **delivery to the recipient** is measured (`recv95` column), when the recipient is online;
   - defaults are the plan's targets: message p95 300 ms, p99 1 s, chat list p95 300 ms, errors 0.1%.
4. **Checked against the real server again:**
   - all pairs blocked → `205/205 messages got no echo; 205/205 never reached the recipient; … no measurements` → **FAIL**;
   - blocks removed, 20 then 40 users → 20: **OK** (recv95 119 ms); 40: FAIL at message p95 507 ms. That is a tiny
     local run with `DEBUG=True`, **not** a capacity number;
   - server killed during step 1, `--keep-going`: old tester → step 2 "**20/40** connected" and "2/1 messages lost";
     new tester → "**40/40** users not connected".
5. **Results:** `make test` → 89 run, OK (6 skipped). Real Postgres + Redis → **95 tests, OK**. `ruff check .` → clean.

**Not done:**
- **Session 014's baseline isn't rerun yet.** Its verdicts are marked unconfirmed in session 014 and the guide.
- The local database now holds 40 load-test users (the 2,000 from session 014 were replaced). A rerun seeds again.
- `run.py` itself (the async part) has no automated test. It was checked by the three real runs above.
- Server error frames (`{"type": "error"}`) are reported but don't fail a step on their own. A lost message does.

## Concepts I learned

### A test that can't fail
- **Simple definition:** a check that says "pass" whatever happens. It gives confidence without evidence.
- **How to catch it:** break the system on purpose and confirm the check says FAIL. Here: block every chat.
- **Everyday example:** a smoke alarm with no battery is silent in a fire *and* in clean air. Press its test button.

### Missing data is not good data
- `pct([])` returns `None`. The old code then did `None or 0` → 0 ms → "fast". Treat "no samples while
  something was sent" as a failure of its own.

### Draining at a boundary
- A message sent 1 s before a step ends can't be judged yet. Either wait for it or ignore it, but never count
  it as fine. We **pause sending** and wait, so every message sent in a step is judged in that step.

### Echo vs delivery
- **Echo:** the sender's own socket gets the message back. That proves it was saved and broadcast. The plan's SLO uses it.
- **Delivery:** the *recipient's* socket gets it. That's what a user feels. They can differ, e.g. if the
  recipient's group membership expired (Codex #7).

## Important code walkthrough

### `loadtest/verdict.py`
```python
if count and value is None:
    found.append(f'{name}: no measurements')
elif value is not None and value > limit:
    found.append(f'{name} {value:.0f}ms > {limit:.0f}ms')
```
- `count` is how many things should have been measured (messages sent, requests made). Something sent but nothing
  measured is a failure. Nothing sent and nothing measured (a quiet step) is fine.

### `Run.drain()` in `loadtest/run.py`
```python
self.paused = True
deadline = time.perf_counter() + self.args.message_timeout
while time.perf_counter() < deadline and (
        self.to_deliver or any(u.pending for u in self.users)):
    await asyncio.sleep(0.1)
self.stats.lost += sum(len(u.pending) for u in self.users)
self.stats.undelivered += len(self.to_deliver)
```
- `pending` (per user) holds messages waiting for their echo. `to_deliver` (shared) holds messages waiting for the
  recipient. Echoes and arrivals remove entries. What's left after the deadline is lost.
- It usually finishes in well under a second, because healthy messages come back in milliseconds.

### Counting who is online
```python
connected = sum(1 for u in run.users if not u.closed)
```
- `read()` sets `closed = True` when its socket ends. Each socket knows its own state, so nothing is forgotten
  when the per-step counters are replaced.

## Problems we encountered
- [P-23 · The load tester could pass a step with zero echoes](../problems-and-solutions.md#p-23--the-load-tester-could-pass-a-step-with-zero-echoes)
- **The first kill test hit the wrong step.** I waited for the header line in the output file, but `print` without
  `flush=True` is buffered, so it appeared only after step 1. I reran with `python -u` and killed the server
  after a fixed 4 s.

## Engineering decisions and trade-offs
- **Pause and drain instead of judging in-flight messages later:** every message sent in a step is judged in that
  step, at the cost of up to 10 s more per step (only when messages are really missing).
- **A separate `verdict.py`:** the rules are the part that was wrong, and they're pure functions, so they get unit tests
  without `aiohttp` in the main requirements.
- **Plan targets as defaults:** a run with no flags now answers the plan's question. Looser limits are still
  available as flags, but you have to ask for them.

## What I should remember
- Make every check fail once on purpose before trusting its "pass".
- `x or 0` turns "unknown" into "perfect". Handle `None` explicitly.
- Judge everything a step started before you leave the step.
- Count state from the things themselves (each socket's `closed`), not from a counter that gets reset.

## Review questions
1. Why did the old tester call a step with zero echoes healthy? Name both reasons.
2. A step sends 10 messages in its last second and none come back. Old tester vs new tester: what does each report?
3. Why does `drain()` pause sending instead of just waiting?
4. Why count online users from `u.closed` rather than `len(users) - drops`?
5. What's the difference between `message_p95_ms` and `delivery_p95_ms`? Which one does the plan's SLO use?
6. How would you check that a new check in `verdict.py` can actually fail?

<details><summary>Answer key</summary>

1. `None or 0` turned the missing p95 into 0 ms, which passes. And unanswered messages counted as lost only once
   they were older than the timeout at summary time, so in a short step none were.
2. Old: lost = 0 (none is 10 s old yet), p95 missing → 0 → OK. New: the drain waits 10 s, then counts all 10 as lost
   (10/10 > 0.1%), and p95 has no measurements → FAIL.
3. Otherwise new messages keep arriving while it waits, so there's always something in flight, and those messages
   would belong to no step.
4. `drops` lives in the per-step `Stats`, which is replaced after each step, so earlier drops are forgotten. Each
   socket's `closed` flag never resets.
5. Echo: send → back on the sender's socket. Delivery: send → arrives at the recipient. The plan uses echo; delivery
   is what users feel and catches problems only the recipient side has.
6. Write a unit test with a row that breaks it (like `test_the_plan_targets_are_the_limits`), and run the real
   tester against a server broken on purpose.
</details>

## Next steps
- Review and merge this PR.
- **Rerun the baseline** with the fixed tester: one Daphne process, `DJANGO_DEBUG=False`, same Mac, plan defaults.
- Codex #7 (24 h group expiry) and #9 (REST read receipts).
