# 008 · T-02: a socket that closes always marks the user offline

- **Date:** 2026-10-10 · **Phase:** Stage 0
- **Task:** T-02 (fixes COR-2) · **Branch:** `t-02-disconnect-marks-offline`
- **Files:** `chats/consumers.py`, `chats/test_consumers.py`, docs
- **Objective:** a failure while leaving the Redis group must not leave the user shown as "online".
  Also find out *why* the failure happened.

## Before we started
- Synced `main`: Dependabot PRs #8–#11 merged (Actions v7, Django 6.1.2, DRF 3.18.3, redis 8.1.0).
  #13 closed as a duplicate. #12 is still open.
- Synced your `.venv` to the new pins and deleted the merged local `t-11` branch.
- Turned on **auto-merge** in the repository settings, at your request. It merges a PR only after the
  ruleset's checks pass.

## What we accomplished
1. **Wrote the test first:** `test_a_failed_group_discard_still_marks_the_user_offline`. It makes the channel
   layer's `group_discard` raise `MaxConnectionsError`, the exact error from the load test, then closes the
   socket. **It failed** with the same error, which reproduced the bug.
2. **Fixed `disconnect()`:** catch and log a `group_discard` failure, then continue to `mark_offline` and
   `touch_last_seen`. **The test passed**, and all 54 tests pass.
3. **Found the root cause** of `MaxConnectionsError` by reading the library source
   ([P-13](../problems-and-solutions.md#p-13--a-burst-of-disconnects-left-users-online-cor-2)): a
   client-side pool limit of 100 connections per process that raises instead of waiting.
4. **Decided not to change the pool size yet.** That's a capacity decision for Stage 1, and it needs a load
   test to choose the right number.

**Not done:** the acceptance check "no presence leftovers after the load test's end-of-run disconnects".
It needs the local stack (Docker) and is planned together with the baseline load test.

## Concepts I learned

### Robust cleanup code
- **Simple definition:** cleanup (closing, releasing, marking offline) must still do its most important
  job when one of its steps fails.
- **Why it matters:** cleanup often runs exactly when things are going wrong: overload, network trouble,
  shutdown. Code that assumes every step succeeds fails at the worst moment.
- **How:** put each risky step in its own `try/except`, **log** the failure (never hide it), and keep going.
  Order the steps so the one users notice comes first or can't be skipped.
- **Common mistake:** a bare `except: pass`. The system then degrades silently, and nobody finds out why.
  We use `logger.exception(...)`, which records the full traceback.
- **When not to:** in normal request handling, an unexpected error should usually propagate, so the request
  fails visibly. Swallowing errors is for cleanup and for optional side effects.

### Connection pools
- **Simple definition:** a pool keeps a set of open connections to reuse, instead of opening a new one for
  every command (opening one is slow, see [PERF-2](../concepts/performance-and-load-testing.md)).
- **The limit:** a pool has a maximum size. When every connection is busy, it either **waits** for one to
  free up (`BlockingConnectionPool`) or **fails immediately** (redis-py's default `ConnectionPool`).
- **In our project:** channels-redis creates one pool per process, shared by every socket in that process,
  with the default limit of 100. A burst of 200 disconnects needs about 200 at once, so about half failed.
- **Trade-off for later:** a bigger pool means more open connections per process, multiplied by the number
  of processes, and the Redis server has its own limit. A blocking pool means waiting, which adds latency.
  We'll choose with measurements in Stage 1.

## Important code walkthrough

### `chats/consumers.py`, `InboxConsumer.disconnect`
```python
async def disconnect(self, code):
    if hasattr(self, 'group'):
        try:
            await self.channel_layer.group_discard(self.group, self.channel_name)
        except Exception:
            logger.exception('inbox: group_discard failed for user %s', self.user.pk)
    if getattr(self, 'user', None) and self.user.is_authenticated:
        await sync_to_async(presence.mark_offline)(self.user.pk, self.channel_name)
        await self.touch_last_seen()
```
- **`hasattr(self, 'group')`:** `group` is only set in `connect()` after a successful login. A socket refused
  with 4401 never joined a group, so there's nothing to discard.
- **`except Exception`, not `except MaxConnectionsError`:** *any* failure here (timeout, connection reset)
  should not block marking offline. `Exception` deliberately leaves out `asyncio.CancelledError`, a
  `BaseException`, so shutdown and cancellation still work normally.
- **Why skipping the discard is safe:** the stale entry in the Redis group expires through channels-redis's
  `group_expiry`. Meanwhile, messages sent to that dead channel just expire unread. That's wasteful, but harmless.
- **`presence.mark_offline` already has its own `try/except redis.RedisError`** (`chats/presence.py`), so
  presence errors never crash the consumer either.

### The test (`chats/test_consumers.py`)
```python
layer = get_channel_layer()
failing = mock.AsyncMock(side_effect=MaxConnectionsError('Too many connections'))

with mock.patch.object(layer, 'group_discard', failing), \
        self.assertLogs('chats.consumers', 'ERROR'):
    await self.close_all()

failing.assert_awaited_once()
self.assertFalse(self.online(self.alice))
```
- **`get_channel_layer()` returns the same object every consumer uses** (a singleton per alias), so patching
  it affects the consumer under test.
- **`AsyncMock`:** `group_discard` is `async`, so the stand-in must be awaitable too.
- **`assertLogs`** proves the failure is *logged*, not silently swallowed. If someone later changes the code to
  `except: pass`, this test fails.
- **`assert_awaited_once()`** proves the failure path was really exercised. Without it, the test could pass
  because `group_discard` was never called.

## Problems we encountered
- [P-13 · A burst of disconnects left users "online"](../problems-and-solutions.md#p-13--a-burst-of-disconnects-left-users-online-cor-2)

## Engineering decisions and trade-offs
- **Fix the symptom now (robust cleanup) and record the root cause for later (pool sizing).** The first is
  safe, small and testable. The second changes capacity behaviour and needs measurements.
- **Log with `logger.exception`.** Failures stay visible in the logs (T-12 will ship them somewhere useful).

## What I should remember
- Write the failing test first. It proves you understood the bug, and it proves the fix.
- Cleanup must do its most important job even when other steps fail. Log; never `pass`.
- "Too many connections" can be a **client-side pool** limit. Read the library before tuning the server.
- When mocking, also assert the mock was actually called.

## Review questions
1. Why does the order of steps in `disconnect()` matter, and what did the old version get wrong?
2. Why `except Exception` and not `except BaseException`?
3. Code reading: what would the test prove if you removed `failing.assert_awaited_once()`? What wouldn't it prove?
4. Debugging: in production you see many `inbox: group_discard failed` log lines at 18:00 every day. What's your first hypothesis, and what would you measure?
5. Design: list two ways to stop `MaxConnectionsError` itself, and one downside of each.

<details><summary>Answer key</summary>

1. The step users notice (mark offline) depended on an earlier, unrelated step succeeding. The old code had
   no error handling, so a `group_discard` failure skipped `mark_offline` and `touch_last_seen`.
2. `BaseException` includes `asyncio.CancelledError` and `KeyboardInterrupt`. Swallowing those would break
   cancellation and shutdown.
3. It would still prove the user ends up offline, but not that the failure path ran. If `group_discard`
   were never called (a refactor skipped it), the test would pass without testing anything.
4. A daily burst of disconnects (people closing the app at the end of the workday, or a scheduled deploy at
   18:00) exhausting the 100-connection pool. Measure concurrent disconnects per process, the pool's in-use
   count, and whether a deploy or restart happens then.
5. (a) Raise `max_connections`: more connections per process × processes, which can hit Redis `maxclients`
   and use more memory. (b) A blocking pool that waits: calls get slower under bursts instead of failing.
   (c) More processes, which spreads the sockets thinner: more servers and more cost.
</details>

## Next steps
- Review and merge the T-02 PR.
- Next: **T-03/T-04** (rate limits; COR-3, where a JSON array or numeric `text` crashes the consumer).
- Later (Stage 1): choose the channel-layer pool size or a blocking pool, with the load test.
