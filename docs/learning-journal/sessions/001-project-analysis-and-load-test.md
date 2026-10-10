# 001 · Project analysis and load test

- **Date:** 2026-10-09 (written afterwards, on 2026-10-10, from `docs/scaling/` and the previous
  session's summary, because the journal didn't exist yet. Details are less certain than in later sessions.)
- **Phase:** before Stage 0, analysis
- **Files:** `chats/management/commands/loadtest_seed.py`, `loadtest/run.py`, `docs/scaling/*`
- **Objective:** find out how many people can be online at once, why it fails, and plan to reach 10,000 online.

## What we accomplished
- **Created** a load test toolkit: a seed command and a step load test client.
- **Ran** the load test against one local server process. 100 online users were healthy and 200
  failed (message p95 1,538 ms). The profile was heavy: about 6× more messages per user than a realistic one.
- **Measured** Postgres connect time vs query time: 6.2 ms vs 0.22 ms.
- **Wrote** the audit (every finding with file:line and evidence), a staged plan
  (now → 1,000 → 10,000 online), an operations runbook with backlog T-01…T-37, and an interview guide.
- **Decided** to target *online* users, not registered users (they're what costs resources), and to
  cap the target at 10,000.
- **Committed** in [session 002](002-review-and-first-commit.md) as `4de99ca`.
- **Not done:** the baseline test with a realistic profile from a second machine. It's still planned.

## Concepts I learned
- **WebSockets and why online users matter:** [http-and-websockets](../concepts/http-and-websockets.md)
- **How a message moves through Channels and Redis:** [django-channels-and-redis](../concepts/django-channels-and-redis.md)
- **Step load testing, p95, utilisation, bottlenecks:** [performance-and-load-testing](../concepts/performance-and-load-testing.md)

## Important code walkthrough

### `loadtest_seed.py`: creating test data safely
```python
if not settings.DEBUG and not opts['force']:
    raise CommandError('DEBUG is off: this looks like production. ...')
deleted, _ = loadtest_users().delete()      # only users with the +998990 prefix AND first_name='loadtest'
```
- **Safety first:**
  - It refuses to run against something that looks like production.
  - It only deletes users matching **two** markers, so a real user can't be caught by accident.
- **`bulk_create`** inserts thousands of rows in a few queries instead of one query per row.
- **Pairing:** users are created in order and paired `(0,1), (2,3)…`. Postgres hands out increasing
  ids, so `user1 < user2` holds and the `Chat` check constraint is satisfied.
- **Tokens are minted directly** with `AccessToken.for_user(user)` plus a longer expiry, so the test
  doesn't spend time on logins. Password hashing is deliberately slow (PERF-9).
- **Output:** `loadtest/tokens.json` with `{user_id, chat_id, token}` per user. It's gitignored.

### `loadtest/run.py`: simulating browsers
- `SimUser.start()` opens `ws://…/ws/inbox/?token=…`. It sends an `Origin` header, because
  `AllowedHostsOriginValidator` rejects sockets without one.
- **Four loops per user**, copying `app.js`:
  - `read()` matches echoes of its own messages to measure delivery time;
  - `ping_loop()` pings every 30 s;
  - `poll_loop()` fetches the chat list every 45 s;
  - `send_loop()`, for active users only, sends at random intervals (`random.expovariate`), like real people.
- **Steps:**
  1. `Run.ramp_to(target)` adds users at `--connect-rate` per second.
  2. `Stats.reset_traffic()` throws away the ramp-up noise.
  3. It holds for `--hold` seconds.
  4. `summarize()` computes p50/p95/p99 and marks the step **failed** if:
     - fewer than 99% of users are connected, or
     - more than 1% of messages are lost, or
     - message p95 is over 500 ms, or chat list p95 is over 1,000 ms.
- **Why random start offsets** (`random.uniform(0, interval)`): otherwise every user pings at the
  same instant and you measure an artificial spike.

## Problems we encountered
- [P-08 · The server fails between 100 and 200 users online](../problems-and-solutions.md#p-08--the-server-fails-between-100-and-200-users-online)

## Engineering decisions
- Target online users, capped at 10,000. Stay on one Django codebase with one primary Postgres. Measure
  before optimising. The plan's ADRs are listed in [decisions/](../decisions/README.md).

## What I should remember
- For chat apps, capacity means **concurrent connections and the work they cause**, not registered users.
- Latency stays flat, then explodes once a resource is around 70–80% busy.
- The cheapest fix is usually removing waste (a new DB connection per call), not new technology.
- A load test only means something if its workload looks like real users.

## Review questions
1. Why does `loadtest_seed` check two markers (phone prefix *and* first name) before deleting?
2. In `run.py`, why are ping and poll start times randomised?
3. One process handled 100 users but not 200. Using the PERF-4 numbers, explain why the jump is so sudden.
4. Name two reasons our first measurement is pessimistic.
5. If you could make only one change to raise capacity, which one would you pick, and why?

<details><summary>Answer key</summary>

1. So a real user whose phone number happens to start with `+998990` is never deleted. Both conditions must match.
2. So the server sees a realistic, spread-out load instead of everyone acting at once.
3. The single DB thread goes from about 42% to about 86% busy. Queueing delay grows like `busy/(1-busy)`,
   so near 100% it explodes.
4. The load client ran on the same machine as the server, and the message rate was about 6× a realistic profile.
5. Reuse database connections (pooling), because 6.2 of the 6.5 ms per call is connecting.
</details>

## Next steps
- Stage 0 security and correctness fixes first (T-01, T-08, T-11…).
- Re-run the baseline with a realistic profile from a second machine.
