# 013 · Fix: leftover presence entries no longer lock users out

- **Date:** 2026-10-11 · **Phase:** Stage 0
- **Task:** follow-up from sessions 011 and 012, not in the backlog · **Branch:** `fix-presence-leak`
- **Files:** `chats/presence.py`, `chats/consumers.py` (one line), `test_helpers.py`, `chats/test_presence.py` (new),
  `chats/test_consumers.py`, `accounts/tests.py`, `chats/tests.py`, docs
- **Objective:** an entry left by a socket that died without `disconnect()` stops counting within 90 s, even
  while the user's other tabs keep pinging.

## Before we started
- PR #20 (T-09) merged as `00f9789`. Branched `fix-presence-leak` from the updated `main`.

## What we accomplished
1. **Found the real cause** ([P-18](../problems-and-solutions.md#p-18--leftover-presence-entries-lived-as-long-as-any-other-tab)):
   a leftover didn't just live "up to 90 s", as session 012 said. It lived **as long as any other tab kept pinging**,
   because all of a user's sockets shared one TTL.
2. **Refactored three tests first** to use the presence functions instead of raw Redis keys (`presence:<id>`).
   They still passed on the old code (73 OK), so the refactor changed nothing.
3. **Wrote the new tests and watched them fail:** 5 unit tests in `chats/test_presence.py` with a frozen clock,
   plus `test_entries_left_by_dead_sockets_do_not_lock_the_user_out` in `RateLimitTests`. Four errored because
   `refresh()` couldn't target one socket, which is the bug itself. One failed on behaviour: a user whose only socket
   died **stayed online**.
4. **Fixed it:** each user is now a Redis **sorted set** `online:<id>`, mapping each socket to the time of its last ping.
5. **Tested against real Redis**, because every other presence test uses `FakeRedis`: `PresenceOnRealRedisTests`.
6. **Results:** test settings → **80 tests, OK (2 skipped**, both need real Redis). Real settings (Docker Postgres +
   Redis) → **80 tests, OK**, including the real-Redis presence test. `ruff check .` → clean.
7. **Real-stack check:** planted a 200-second-old "dead" entry for Tester A, then opened the app. On connect, the dead
   entry was deleted, `socket_count` was 1, Tester A was online and Tester B (not connected) offline.

**Not done:**
- A rolling deploy with old and new code running side by side would track presence in two different keys for a moment.
  We run one process, so this doesn't apply yet. Old `presence:<id>` keys expire within 90 s, because nothing renews them now.

## Concepts I learned

### Sorted set (Redis `ZSET`)
- **Simple definition:** like a set, but each member has a number, its **score**, and Redis keeps members ordered by it.
- **Commands we use:** `ZADD key {member: score}` (add, or update the score), `ZREM` (remove), `ZCOUNT key min max`
  (how many scores in a range), `ZREMRANGEBYSCORE key min max` (delete a range).
- **Score ranges:** inclusive by default. A `(` prefix makes a bound exclusive: `(910` means "greater than 910".
  `-inf` and `+inf` mean no limit.
- **Our use:** score = time of the socket's last ping. "Live sockets" = `ZCOUNT key (now - 90) +inf`.

### One expiry per item, not per group
- **Before:** one TTL on the whole set, renewed by every ping. A group with one live member never expires, so its
  dead members never do either.
- **After:** each member carries its own time. Reads ignore old members, and `socket_count` deletes them. The key's
  TTL remains only to clean up users who went quiet entirely.
- **Everyday example:** a guest list where the *whole list* is thrown away after 90 s without visitors. As long as one
  guest keeps coming back, everyone who ever signed in stays on it. Better: write the time next to each name.

### Fakes in tests
- `FakeRedis` (in `test_helpers.py`) replaces Redis so tests are fast and need no server. But a fake only helps if it
  behaves like the real thing. Mine didn't understand `(910` at first, the consumer crashed inside the tests, and the
  suite **hung**. That fits session 011's hypothesis: a failing consumer test can leave the run hanging.
- So there's also one test against **real** Redis, which runs in CI's `test-postgres-redis` job.

## Important code walkthrough

### `chats/presence.py`
```python
def _touch(user_id, channel_name):
    pipe = client().pipeline()
    pipe.zadd(key(user_id), {channel_name: now()})
    pipe.expire(key(user_id), TTL_SECONDS)
    pipe.execute()
```
- `mark_online` and `refresh` both call this. `refresh` now needs the **channel name**, so a ping renews only its own
  socket. The consumer passes `self.channel_name`.
- `pipeline()` sends both commands in one round trip.

```python
def socket_count(user_id):
    pipe = client().pipeline()
    pipe.zremrangebyscore(key(user_id), '-inf', f'({_live_since()}')  # drop dead entries
    pipe.zcount(key(user_id), _live_since(), '+inf')
    return pipe.execute()[1]
```
- `_live_since()` is `now() - 90`. The first command deletes every entry *older* than that (exclusive `(`), and the
  second counts the rest.
- Deleting here keeps the set small. `socket_count` runs once per connect, so the cost is tiny.
- `is_online` and `online_map` only **count** recent entries and don't delete. They're reads, called often.

### `now()`, the clock seam
```python
def now():
    return time.time()
```
- Tests replace it with `lambda: self.clock` and move time forward by hand, so "90 s later" takes no real time.
- `time.time()` (wall clock), not `time.monotonic()`: the score is stored in Redis and compared by other processes.
  A monotonic clock only means something inside one process.

## Problems we encountered
- [P-18 · Leftover presence entries lived as long as any other tab](../problems-and-solutions.md#p-18--leftover-presence-entries-lived-as-long-as-any-other-tab)
- **The suite hung** while `FakeRedis` couldn't parse `(…`. Each consumer test crashed inside the consumer. Fixed by
  making the fake understand the syntax. Now there's evidence for session 011's guess about the earlier hang
  (still a *Hypothesis*: I didn't trace exactly which await blocks).

## Engineering decisions and trade-offs
- **Per-socket timestamps rather than "always run cleanup on a crash" (`try/finally` around the consumer):** a
  `finally` can't run when the whole process is killed, which happens on every deploy. Timestamps cover both.
- **A new key name (`online:`)** instead of migrating data: old keys are plain sets, and sorted-set commands on them
  fail with `WRONGTYPE`. The old ones expire within 90 s.
- **Wall-clock time across processes:** servers' clocks must roughly agree. With NTP that's within milliseconds,
  tiny compared with 90 s.

## What I should remember
- One expiry for a group, renewed by any member, means a dead member never expires. Time each member.
- `finally` doesn't run when a process is killed. Design state so that a dead owner's data ages out by itself.
- A fake must behave like the real thing, and something must test the real thing.
- "It expires by itself" is a claim. Test it in the case where something *else* keeps it alive.

## Review questions
1. With the old design, why could a leftover entry live for hours?
2. Why doesn't wrapping the consumer in `try/finally` fully fix this?
3. Code reading: what does `f'({_live_since()}'` mean to Redis, and why exclusive?
4. Why `time.time()` here, when the token bucket uses `time.monotonic()`?
5. Why a new key name instead of keeping `presence:<id>`?
6. Testing: why add a test against real Redis when the fake tests already pass?

<details><summary>Answer key</summary>

1. The TTL was on the whole set, and every ping from *any* of the user's sockets renewed it. While one tab stayed
   open, the set (with the dead entry inside) never expired.
2. `finally` runs when code raises, not when the process is killed (deploys, crashes, OOM). Then no cleanup code runs
   at all, so the data itself must age out.
3. "Greater than (not equal to) now − 90". Combined with `-inf`, it deletes every entry whose last ping is older than
   90 s. Exclusive matches the count, which keeps entries *at* the boundary.
4. The score is stored in Redis and compared across processes and restarts. `monotonic()` has no fixed starting point,
   so its values from different processes can't be compared. The bucket lives in one socket's memory, where
   `monotonic()` is right because it never jumps when the wall clock is adjusted.
5. Old keys are plain sets. `ZADD` or `ZCOUNT` on them fails with `WRONGTYPE`. A new name avoids that, and the old keys
   expire within 90 s because nothing renews them any more.
6. Every other presence test replaces Redis with `FakeRedis`. If the fake differs from Redis (as it did with `(`), the
   tests can pass while production fails. One real test catches that.
</details>

## Next steps
- Review and merge this PR.
- Stage 0's last item: the **baseline load test** (realistic profile, from a second machine).
