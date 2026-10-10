# 012 · Hotfix: quiet WebSockets crashed after 5 seconds (redis-py 8)

- **Date:** 2026-10-11 · **Phase:** Stage 0
- **Task:** hotfix, not in the backlog · **Branch:** `fix-redis-socket-timeout`
- **Files:** `root/settings.py`, `chats/test_channel_layer.py` (new), docs
- **Objective:** a WebSocket with no traffic must stay open, as it did with redis-py 7.

## How we found it
While checking T-09 in a real browser ([session 011](011-t09-gap-fetch-and-jitter.md)), the client got stuck in a
reconnect loop. The server log showed `Timeout reading from localhost:6379` inside the consumer. Following that thread
gave the root cause in [P-17](../problems-and-solutions.md#p-17--every-quiet-websocket-crashed-after-5-seconds-redis-py-8).

## What we accomplished
1. **Reproduced it outside Django** with a 10-line script: a 5 s `bzpopmin` on an empty key raised `TimeoutError`
   at 5.01 s, 3 out of 3 times, with redis-py 8's defaults. With `socket_timeout=None`, it returned normally.
2. **Wrote a failing test** (`chats/test_channel_layer.py`): wait on a quiet channel for 7 s and expect *our own*
   timeout, not a Redis error. With the real settings it **failed** with `redis.exceptions.TimeoutError` at 5.02 s.
   With the test settings (in-memory layer) it's skipped.
3. **Fixed it** in `CHANNEL_LAYERS`: `{'address': REDIS_URL, 'socket_timeout': 10}`.
4. **Results:** the new test passes (it ends at 7.0 s, as designed). The full suite passes with the **real** settings
   (Docker Postgres 17 + Homebrew Redis 8.10): 69 tests in 45 s. With the test settings: 69 tests, 1 skipped.
   `ruff check .` → clean.

**Not done:**
- A consumer that crashes for *any* reason still leaks its presence entry until the 90 s TTL expires, and enough
  leftovers trip the 5-socket cap. That's a robustness gap worth its own task.
- `main` had this bug from the Dependabot merge on 2026-10-10 until this fix merges.

## Concepts I learned

### Blocking reads and socket timeouts
- **Blocking read:** `BZPOPMIN key 5` asks Redis to *wait* up to 5 s for an item, then answer "nothing". It's how
  channels-redis waits for messages without polling in a tight loop.
- **Socket timeout:** how long the *client* waits for any reply before giving up.
- **The rule:** the client's socket timeout must be *longer* than any server-side wait you ask for. Otherwise the
  client gives up just before the answer arrives. 10 s > 5 s.
- **Why not `None` (no timeout)?** If Redis hangs completely, a read would then wait forever. A timeout longer than
  the expected wait still catches a dead server.

### A changed default is a breaking change
Our code didn't change. A library's default did, in a major version (7 → 8). Dependabot opened the PR and CI passed,
because no test held a socket open and quiet for 5 s. The fix for the process: read the changelog of major bumps,
and test the "nothing happens for a while" case of long-lived connections.

## Important code walkthrough

### `root/settings.py`
```python
'CONFIG': {'hosts': [{'address': REDIS_URL, 'socket_timeout': 10}]},
```
- A host can be a URL string or a dict. With a dict, channels-redis passes every key except `address` to
  `redis.asyncio.ConnectionPool.from_url(address, **host)` (`channels_redis/utils.py:80-83`), so `socket_timeout`
  reaches redis-py.

### `chats/test_channel_layer.py`
```python
channel = await self.layer.new_channel()
with self.assertRaises(asyncio.TimeoutError):
    await asyncio.wait_for(self.layer.receive(channel), timeout=self.layer.brpop_timeout + 2)
```
- `receive()` on a channel nobody sends to waits forever, looping over 5 s blocking reads.
- `wait_for(..., 7)` stops it after 7 s with `asyncio.TimeoutError`. That's the *expected* ending.
- With the bug, the first 5 s read raises `redis.exceptions.TimeoutError` instead. That's a different class
  (it inherits from `RedisError`, not from the built-in `TimeoutError`), so `assertRaises` doesn't accept it and the test fails.
- `skipTest` when the layer isn't Redis: the SQLite settings use the in-memory layer, where the bug can't happen.

## Problems we encountered
- [P-17 · Every quiet WebSocket crashed after 5 seconds (redis-py 8)](../problems-and-solutions.md#p-17--every-quiet-websocket-crashed-after-5-seconds-redis-py-8)
- Port conflicts for the local run: Homebrew Postgres 14 owned `localhost:5432` (stopped it, with your OK; restart
  with `brew services start postgresql@14`). Port 8000 belongs to another project, so Django ran on 8001.

## Engineering decisions and trade-offs
- **Raise the timeout instead of pinning `redis<8`:** pinning only hides the problem until the next upgrade, and
  redis-py 8 is the supported line. The setting documents *why* it's needed.
- **10 s, not `None`:** keeps a safety net against a hung Redis.
- **A separate PR from T-09:** it's a regression on `main` that affects everyone. It should merge first, on its own.

## What I should remember
- A client timeout must be longer than the server-side wait you ask for.
- Major version bumps can change defaults. Read the changelog.
- Test long-lived connections when they're idle, not only when they're busy.
- A browser check found two bugs that 72 green tests didn't. Run the real thing.

## Review questions
1. Explain in two sentences why every quiet socket crashed after about 5 s.
2. Why did CI stay green?
3. Why `socket_timeout: 10` and not `None`?
4. Code reading: why does the test expect `asyncio.TimeoutError`, and why does the bug make it fail?
5. Why did one crash per socket end up locking the user out completely?

<details><summary>Answer key</summary>

1. channels-redis asks Redis to block for up to 5 s waiting for a message. redis-py 8 gives up on any reply after
   5 s by default, so it raised just before Redis answered, and the exception killed the consumer.
2. The SQLite job uses the in-memory channel layer, which doesn't use Redis. The Postgres + Redis job's tests are
   short and busy: no socket sat quiet for 5 s.
3. With `None`, a hung Redis would block a read forever. 10 s is longer than the 5 s wait but still detects a dead server.
4. `wait_for` ending our 7 s wait is the normal outcome. With the bug, `redis.exceptions.TimeoutError` (a
   `RedisError`, not a built-in `TimeoutError`) is raised at 5 s first, so `assertRaises(asyncio.TimeoutError)` fails.
5. A crashed consumer skips `disconnect()`, so its entry stays in the presence set. After 5 leftovers,
   `socket_count` reached the cap, and every new socket was refused with 4429 until the TTL expired.
</details>

## Next steps
- Merge this hotfix first. Then update the T-09 PR and finish its browser check.
- Later: make a crashed consumer clean up its presence entry (or shorten how long leftovers count).
