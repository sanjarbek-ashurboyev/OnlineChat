# 010 · T-04: WebSocket input checks, a frame limit per socket, at most 5 sockets per user

- **Date:** 2026-10-10 · **Phase:** Stage 0
- **Task:** T-04 (fixes COR-3, SEC-5) · **Branch:** `t-04-ws-input-validation`
- **Files:** `chats/consumers.py`, `chats/ratelimit.py` (new), `chats/presence.py`, `chats/test_consumers.py`,
  `chats/test_ratelimit.py` (new), docs
- **Objective:** no frame a client sends can crash the consumer, and one client can't flood the database
  through the WebSocket.

## Before we started
- PR #18 (T-03) had already been merged by auto-merge, **without** the second commit I pushed to it (the
  learning-tracker fix). See [P-15](../problems-and-solutions.md#p-15--a-commit-pushed-to-a-pr-after-auto-merge-never-reached-main).
  I cherry-picked that commit onto this branch and added a rule to `GOTCHA.md`.
- Already done before T-04: the 4,000-character cap on message text, in both the consumer and
  `MessageSerializer` (`MAX_MESSAGE_LENGTH` in `chats/models.py`). The T-04 test "4,001 characters rejected"
  was already covered by `test_text_is_validated`.

## What we accomplished
1. **Wrote 6 tests first:** 3 for `TokenBucket` on its own and 3 for the consumer.
   - Wrong-type payloads (`["a","list"]`, `42`, `"a string"`, `null`, and `text` as a number, list or object):
     the first one **crashed the consumer** with `AttributeError: 'list' object has no attribute 'get'`. That's
     COR-3, reproduced. Every later check then timed out on the dead socket.
   - A burst of 20 messages: **all 20 were saved** (no limit).
   - A 6th socket for the same user: **accepted** (no cap).
2. **Fixed it:**
   - `receive()` checks the payload is a JSON object and that `text` is a string. Otherwise it sends an error frame.
   - Every frame spends a token from a per-socket `TokenBucket(rate=1, burst=10)`. With none left: `"Slow down."`.
   - `connect()` refuses a user's 6th socket with close code **4429**.
3. **Result:** `make test` → **68 tests, OK**. `ruff check .` (0.16.10) → clean. `makemigrations --check` → no changes.

**Not done:**
- The optional database `CHECK (length(text) <= 4000)` from the T-04 spec. Both write paths (REST and WebSocket)
  already enforce the limit, and a constraint on the message table needs the careful migration rules (R-12).
  Worth doing later, with the other migrations.
- A test for "Redis down at connect → the socket is still allowed". `socket_count` returns 0 on a Redis error,
  copying the pattern the other presence helpers use, but no test covers that path.
- Load-test acceptance ("none of the abuse tests crash the consumer" under load) is planned with the baseline load test.

## Concepts I learned

### Token bucket
Full explanation, with a timeline: [concepts/rate-limiting.md](../concepts/rate-limiting.md#websocket-frames-a-token-bucket-per-socket-t-04).
In short, a bucket of 10 tokens refills at 1 per second, and each frame spends one. Bursts are fine; a
sustained flood is cut to 1 frame per second.

### Validate the *type* before using a value
- **Simple definition:** `json.loads` can return a dict, a list, a string, a number, `True/False` or `None`.
  Code that calls `.get()` or `.strip()` assumes one of them.
- **Why it matters here:** in a consumer, an unexpected exception closes the socket (code 1011). The
  client reconnects, which costs a JWT check, presence writes and group joins. So one bad frame becomes extra load.
- **How:** check with `isinstance` at the boundary, where data enters the program, and answer with an
  error frame. After that check, the rest of the code can trust the type.
- **Example:** `json.loads('42')` returns `42`. `42.get('action')` raises `AttributeError`.

### Close codes 4000–4999
- WebSocket close codes from 4000 to 4999 are free for applications to use. We have **4401** ("not signed
  in", like HTTP 401) and now **4429** ("too many sockets", like HTTP 429).
- **Caveat:** we close *before* accepting, so the browser sees a refused handshake (code 1006), not 4429.
  Our client then just retries with backoff of up to 15 s (`assets/app.js:443`), and gets in once a tab closes.
  The test client (`WebsocketCommunicator`) does see 4429.

## Important code walkthrough

### `chats/consumers.py`, `receive()`: order of checks
```python
async def receive(self, text_data=None, bytes_data=None):
    if not self.bucket.take():
        await self.send_error('Slow down.')
        return
    try:
        payload = json.loads(text_data or '')
    except json.JSONDecodeError:
        ...
    if not isinstance(payload, dict):
        await self.send_error('Expected a JSON object.')
        return
    await self.touch_last_seen()
    ...
```
- **The bucket is checked first,** before parsing and before any database work. A refused frame costs
  almost nothing. Every frame counts, pings included, because `touch_last_seen()` writes to the database on
  every frame (T-15 will reduce that).
- **The type check comes before `touch_last_seen()`,** so garbage doesn't cause a database write.
- Later, `text = payload.get('text') or ''`, then `isinstance(text, str)`. A missing or `null` text still
  gives the old "must not be empty" error. A number gives "text must be a string."

### `chats/consumers.py`, `connect()`: the socket cap
```python
if await sync_to_async(presence.socket_count)(self.user.pk) >= MAX_SOCKETS_PER_USER:
    await self.close(code=CLOSE_TOO_MANY_SOCKETS)
    return
self.bucket = TokenBucket(rate=FRAMES_PER_SECOND, burst=FRAME_BURST)
```
- **`presence.socket_count`** is `SCARD presence:<id>`: the number of channel names in the user's
  presence set, one per open socket. We already keep that set for "online" status, so nothing new is stored.
- **Soft cap:** two sockets connecting at the same instant can both read 4 and both get in. A strict cap would
  need an atomic Redis operation. That isn't worth it for a limit whose job is to stop "1,000 tabs", not "6".
- **Fail open:** if Redis fails, `socket_count` returns 0, so users can still connect. Same choice as T-21 for throttles.

### Freezing time in tests
```python
patcher = mock.patch('chats.ratelimit.time.monotonic', lambda: self.now)
```
- The bucket refills with time. On a slow CI machine, 20 messages might take more than a second, so a
  token would refill and the test would fail **sometimes**. That's a "flaky" test.
- Replacing the clock with `lambda: self.now` makes time stand still until the test moves it (`self.now += 1`).
- We patch `chats.ratelimit.time.monotonic`, **where the code looks it up**, not some other module's `time`.

## Problems we encountered
- [P-15 · A commit pushed to a PR after auto-merge never reached `main`](../problems-and-solutions.md#p-15--a-commit-pushed-to-a-pr-after-auto-merge-never-reached-main)

## Engineering decisions and trade-offs
- **Count every frame, not only messages.** Decision 0.2 talks about "messages". But reads and pings also
  write to the database, so a ping flood is a database flood too. The client pings rarely, so 1 per second is plenty.
- **Numbers from Decision 0.2:** burst 10, 1 per second, 5 sockets. They're constants at the top of
  `consumers.py`, not settings. Unlike the DRF rates, nobody has needed to change them yet.
- **No client change.** The client already shows error frames and reconnects with backoff.

## What I should remember
- Check the type of anything that came from `json.loads` before calling methods on it.
- In a consumer, an exception means a dropped socket and a reconnect: extra load, not just an error.
- Put the cheapest check first (the bucket), and the expensive work (the database) last.
- Tests involving time: freeze the clock, or they'll be flaky.
- With auto-merge on, check the PR is still open before pushing to it.

## Review questions
1. Name three JSON values that would have crashed the old `receive()`, and the line each one crashed on.
2. Why is the bucket check the first line of `receive()`, before `json.loads`?
3. Code reading: with `burst=10, rate=1`, a client sends 10 frames, waits 3 seconds, then sends 10 more. How many of the second 10 pass?
4. Why does the 6th-socket test expect 4429, while a real browser would see 1006?
5. Testing: what would go wrong if the burst test didn't patch `time.monotonic`?
6. Design: the socket cap reads the presence set. What could make it refuse a user who really has fewer than 5 tabs?

<details><summary>Answer key</summary>

1. A list or a number or a string (`payload.get(...)` → `AttributeError`), and `{"chat_id": 1, "text": 5}`
   (`.strip()` on an int → `AttributeError`).
2. It's the cheapest check, and it stops a flood before any work: parsing, the `last_seen` database write,
   chat lookups. A refused frame costs almost nothing.
3. 3. After the first 10, the bucket is empty. Three seconds refill 3 tokens.
4. The consumer closes *before* accepting, which rejects the handshake. Browsers report a rejected handshake as
   1006 and don't see our code. Channels' test client passes the code through.
5. On a slow machine the burst could take longer than a second. A token would refill mid-test, so 10 messages
   would be saved instead of 9. The test would fail now and then: flaky.
6. Leftover entries for sockets that died without `disconnect()` running, e.g. a crashed worker. They expire with
   the presence TTL (90 s). But a live tab's pings refresh the whole set, so leftovers can last while the user is online.
</details>

## Next steps
- Review and merge the T-04 PR.
- Next in the suggested order: **T-09** (fetch messages missed during a reconnect, plus reconnect jitter; COR-1, COR-4).
- Later: the optional DB `CHECK` on message length, with the migration rules.
