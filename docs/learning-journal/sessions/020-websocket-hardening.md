# 020 · Codex audit: WebSocket hardening

- **Date:** 2026-10-11 · **Phase:** Stage 0
- **Task:** findings H-01, M-01, M-02 and M-05 from [Codex's second audit](../../scaling/05-codex-audit-2026-10-11.md)
  · **Branch:** `fix-websocket-hardening`
- **Files:** `chats/middleware.py`, `chats/consumers.py`, `chats/presence.py`, `chats/test_consumers.py`,
  `chats/test_presence.py`, `test_helpers.py`, docs
- **Objective:** an open socket loses its rights when its token expires or its account is disabled; the
  5-socket limit holds under concurrency; no socket outlives its channel group; and odd input gets an error,
  not a crash.

## Before we started
- PRs #28 and #29 merged (`c2e7609`). Branched `fix-websocket-hardening` from the updated `main`.
- Found that access tokens last **5 minutes** (no `SIMPLE_JWT` settings, so SimpleJWT's default) and that
  `app.js` already answers close code 4401 with "renew the token, then reconnect".
- **Your choice:** close at token expiry and let the browser reconnect, over renewing the token on the open
  socket or longer tokens ([decision 006](../decisions/006-socket-rights-end-with-the-token.md)).

## What we accomplished
1. **Wrote 7 consumer tests first.** On the old code: **2 failures + 6 errors**:
   - 8 sockets opened at once → `8 != 5` (M-01);
   - a 5,000-digit number → `ValueError` crashed the consumer (M-05);
   - `a\u0000b` was saved (M-05; on SQLite, Postgres would refuse it), `a\ud800b` → `UnicodeEncodeError` crash;
   - token expiry, a disabled account, and the lifetime cap: no close ever came (H-01, M-02).
2. **H-01:** the middleware now also returns the token's `exp`. Each socket runs a small background task,
   `watch_rights()`, which sleeps until the deadline or for 60 s, whichever comes first. It closes with 4401 at the
   deadline, or when `still_active()` says the account was disabled. A failed check is logged and retried; the
   deadline still holds.
3. **M-02:** the deadline is `min(token expiry, connect time + 12 h)`. `channels_redis` forgets group members after
   24 h, so no socket can outlive its membership. A test asserts `MAX_SOCKET_SECONDS < group_expiry`, so a future
   settings change can't quietly break it.
4. **M-01:** `presence.admit()` prunes dead entries, counts, and adds this socket in **one Lua script**. If the
   setup after it fails, `connect()` gives the slot back.
5. **M-05:** `json.loads` errors are caught as `ValueError` (its subclass `JSONDecodeError` included). Message text
   goes through REST's own `MessageSerializer`, so both doors reject the same things: blank, too long, NUL,
   lone surrogates. The socket's error messages are now REST's wording (e.g. "This field may not be blank.").
6. **Results:**
   - All 7 new consumer tests pass, plus 4 new presence tests (2 on the fake, 2 on real Redis: 8 threads at once →
     **exactly 5** admitted by the real Lua script).
   - `make test` → **112 run, OK (8 skipped)**. Real Postgres + Redis → **118 tests, OK**. `ruff check .` → clean.
   - **Real browser, real server** (a scratch Playwright script, not committed): access token valid for 20 s plus a
     real refresh token → the server closed the socket after **18.6 s with 4401**; the page called
     `/auth/token/refresh/` (200), reconnected with a new token, showed a message sent **during** the gap, then a
     live one, in order, and stayed signed in.

**Not done:**
- **The load tester doesn't reconnect every 5 minutes** like a browser now does (its tokens last hours). Capacity
  numbers ignore that churn: about 33 reconnects a second at 10,000 online.
- Up to **60 s** between disabling an account and its sockets closing.
- `presence.mark_online` and `presence.socket_count` are now used only by tests. I kept them as test helpers.
- Deep JSON nesting: the audit didn't confirm it as a bug, so it isn't handled specially.

## Concepts I learned

### Authentication is a moment; authorization must last
- **Simple definition:** checking a token proves who someone was *when it was checked*. A long connection must
  check again, or it keeps rights that have ended.
- **Everyday example:** a concert wristband checked at the gate. If the event ends at 11, security still has to
  clear the hall at 11; the wristband check at 7 doesn't cover that.

### Atomic operations and Lua in Redis
- **Atomic:** nothing else can happen in the middle. Redis runs one command or one Lua script at a time, so a script
  that counts and then adds can't be interleaved with another socket's count.
- **Why not two commands?** Between "count = 4" and "add", another request can also count 4. We saw 8 get in.

### A background task per connection
- `asyncio.create_task(...)` runs a coroutine alongside the consumer's normal message handling. It must be
  **cancelled** in `disconnect()`, or it outlives the socket.

### Same rules on every door
- REST and the socket both create messages. Running both through `MessageSerializer` means a rule added to one
  applies to the other (the P-20 lesson again).

## Important code walkthrough

### `chats/consumers.py`: `watch_rights()`
```python
while True:
    await asyncio.sleep(max(0, min(self.deadline - time.time(), AUTH_RECHECK_SECONDS)))
    if time.time() >= self.deadline:
        break
    try:
        if not await self.still_active():
            break
    except Exception:
        logger.exception('inbox: account check failed for user %s', self.user.pk)
await self.close(code=CLOSE_UNAUTHENTICATED)
```
- Sleeps at most 60 s, and never past the deadline, so the token's expiry is exact.
- `except Exception` doesn't catch `asyncio.CancelledError` (it's a `BaseException`), so `disconnect()` can still
  cancel the task.

### `chats/presence.py`: the admit script
```lua
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', '(' .. ARGV[1])
if redis.call('ZCOUNT', KEYS[1], ARGV[1], '+inf') >= tonumber(ARGV[2]) then
    return 0
end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
redis.call('EXPIRE', KEYS[1], ARGV[5])
return 1
```
- The same three steps the old code did in separate calls: drop entries older than 90 s, count, add.
- `FakeRedis.eval` (in `test_helpers.py`) redoes it with its Python commands; the real-Redis tests run the real
  script, so the fake can't hide a Lua mistake.

### `chats/consumers.py`: text checks
```python
serializer = MessageSerializer(data={'text': text})
if not serializer.is_valid():
    await self.send_error(serializer.errors['text'][0], chat_id=chat.pk)
    return
text = serializer.validated_data['text']  # trimmed
```
- The `isinstance(text, str)` check stays in front, because DRF's `CharField` would turn `123` into `'123'`.

## Problems we encountered
- [P-27 · Five sockets opened at once let eight in](../problems-and-solutions.md#p-27--five-sockets-opened-at-once-let-eight-in)
- [P-28 · Docker's Redis came back without its port](../problems-and-solutions.md#p-28--dockers-redis-came-back-without-its-port):
  on real settings, nearly every consumer test failed to connect to Redis. Not a code problem; I recreated the
  container.
- **A killed test run left its database behind**, so the next run stopped at Django's "delete the test database?"
  prompt (`EOFError` with no terminal). Use `--noinput` for runs nobody is watching.
- **My first browser check used Django's in-process test client** to post messages, which uses the host `testserver`
  and was refused by `ALLOWED_HOSTS`. Switched to real HTTP requests to the running server.

## Engineering decisions and trade-offs
- [Decision 006](../decisions/006-socket-rights-end-with-the-token.md): close at expiry rather than renew on the socket.
- **One task per socket** instead of checking on every frame: it also catches sockets that only listen, and costs one
  query a minute rather than one per frame.
- **4401 for the 12 h cap too:** the browser renews and reconnects either way; a separate code would add a branch to
  `app.js` for no visible difference.

## What I should remember
- A token check at connect time covers only that moment. Long connections need a deadline and a re-check.
- Count-then-add in two calls is a race; one Lua script isn't.
- Membership in a channel-layer group expires; a socket must not outlive it.
- Catch `ValueError` around `json.loads`, not only `JSONDecodeError`.
- Share validation between REST and the socket by calling the same serializer.

## Review questions
1. Before this change, what could a user do with a socket opened just before their account was disabled?
2. Why does `watch_rights()` sleep for `min(deadline - now, 60)` rather than always 60 s?
3. Why did 8 sockets get in when the limit was 5? Why can't it happen with the Lua script?
4. How does the 12-hour cap fix the 24-hour group expiry problem?
5. Why keep the `isinstance(text, str)` check when the serializer validates the text anyway?
6. What new load does closing every socket at token expiry add, and why isn't it in our load-test numbers?

<details><summary>Answer key</summary>

1. Keep sending and receiving messages for as long as the socket stayed open (days, in principle). The `is_active`
   check ran only in the middleware, at connect time.
2. So the socket closes exactly when its token expires, not up to 60 s later. The 60 s cap is for the account check.
3. Each socket counted first and added itself only after two more awaits (`group_add`, `accept`), so all 8 counted
   before any added. Redis runs a script alone: the next socket's count runs after this one's add.
4. The socket closes before 12 h, the browser reconnects, and `connect()` joins the group again, so membership is
   always less than 12 h old, below the 24 h expiry.
5. DRF's `CharField` converts numbers to strings, so `123` would become the message "123". The socket protocol
   says text must be a string.
6. About one reconnect per tab every 5 minutes: token check, presence write, group join, `last_seen` write, and a
   REST gap fetch plus chat-list reload. The load tester's tokens last hours, so it never reconnects.
</details>

## Next steps
- Review and merge this PR.
- Make the load tester reconnect at token expiry (or use 5-minute tokens), then rerun the baseline.
- Next audit group: frontend session lifecycle (H-04, H-06, M-12, L-03).
