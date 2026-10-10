# 011 · T-09: fetch what the socket missed, reconnect with jitter, close codes the browser can see

- **Date:** 2026-10-11 · **Phase:** Stage 0
- **Task:** T-09 (fixes COR-1, COR-4, COR-5) · **Branch:** `t-09-gap-fetch-jitter`
- **Files:** `chats/views.py`, `chats/consumers.py`, `assets/app.js`, `chats/tests.py`, `chats/test_consumers.py`, docs
- **Objective:** after a reconnect, the open chat shows every message sent while the socket was down. Reconnects
  after a restart are spread out instead of arriving all at once.

## Before we started
- PR #19 (T-04) merged as `66060a7`. Branched `t-09-gap-fetch-jitter` from the updated `main`.
- Read [Decision 0.3](../../scaling/02-plan.md): gap fetch with `Message.id` as the cursor, plus full jitter, in one change.

## What we accomplished
1. **Wrote the tests first, and watched them fail:**
   - `?after=<id>` returns only newer messages, oldest first: **failed** (it returned all three, newest first).
   - `?after=abc`, `-1`, `1.5` or empty → 400: **failed** (200).
   - Disconnect Bob, send 3 messages, reconnect Bob: the socket replays nothing, and `?after=` returns exactly
     the 3. **Failed** (it returned 4, including the one Bob had already seen).
   - Refused sockets (4401, 4429) must complete the handshake *before* closing: **failed** with
     "refused before the handshake: a browser would see 1006". COR-5 confirmed ([P-16](../problems-and-solutions.md#p-16--our-websocket-close-codes-never-reached-the-browser-cor-5)).
2. **Server:** `MessageListCreateAPIView.get_queryset` supports `?after=`. The consumer refuses a socket by
   accepting, then closing (`InboxConsumer.refuse`).
3. **Client (`assets/app.js`):** on a *reconnect*, `onopen` calls `catchUp()` for the open chat and reloads the
   sidebar. The backoff uses full jitter. The "token expired" path goes through the same backoff.
4. **Result:** `make test` → **72 tests, OK**. `ruff check .` → clean. `makemigrations --check` → no changes.
   `node --check assets/app.js` → syntax OK.
5. **Found and fixed my own T-04 mistake:** I had inserted `RateLimitTests` in the middle of `MessagingTests`,
   so `test_a_message_sent_over_rest_reaches_open_sockets` had silently moved into `RateLimitTests`. It still ran
   and passed, just in the wrong class. Moved it back, with the new reconnect test.

6. **Browser check (2026-10-11, after Docker was started).** Ran the real stack (Docker Postgres, Redis, Django on
   port 8001) and drove a Chrome page as "Tester A", with "Tester B" sending:
   - A live message arrived through the socket. ✅
   - I stopped the server, added 2 messages from Tester B directly in the database, then restarted. The client
     reconnected and requested `?after=<last id>`. Both messages appeared in order, with no duplicates. ✅ (done twice)
   - A probe socket received close code **4429** in the browser, not 1006. The COR-5 fix works in a real browser. ✅
   - **It found a bug in my client code:** a refused socket is now accepted first, so `onopen` fired, reset the backoff
     to 0 and ran a catch-up. A user at the socket cap retried about once a second, forever: **142 connects in about 2
     minutes**. Fixed in a second commit: the client pings on open and treats the **first frame from the server** as
     "connected". Re-checked with the cap full (5 fake presence entries for 40 s): 4 refused attempts with growing
     waits and 0 catch-up requests, then 1 connection and exactly 1 catch-up once the entries expired. ✅
   - **It also found a regression on `main`:** quiet sockets crashed after 5 s (redis-py 8). That's fixed separately in
     PR #21, see session 012. The browser checks above ran with that fix applied locally.
   - Small leftover: right after a reconnect, the open chat's sidebar row can show its unread badge for a moment. The
     next sidebar reload clears it (the database already has the messages as read).

**Not done:**
- Load test of a restart with jitter (acceptance), planned with the baseline load test.

## Concepts I learned

### At-most-once delivery and the gap fetch
Full guide: [concepts/reliable-delivery-and-reconnects.md](../concepts/reliable-delivery-and-reconnects.md).
In short, the channel layer is a *notification* system that can lose things. Postgres is the truth. After
reconnecting, ask Postgres for everything after the last id you've shown.

### Cursor
- **Simple definition:** a value that marks "where I am" in a list, so the next request continues from there.
- **Why an id and not a time:** ids only grow and are unique. Two messages can have the same `created_at`,
  so "after 12:00:00.123" could skip one.
- **Compared with page numbers:** `?page=2` shifts when new messages arrive. `?after=41` always means the same thing.

### Full jitter
A random wait between 0 and the backoff (`Math.random() * backoff`). After a server restart, 10,000 clients
spread their reconnects over the window instead of all arriving in the same millisecond.

### Refusing a WebSocket so the client knows why
- Close **before** `accept()`: HTTP 403, and the browser sees **1006** ("abnormal closure"). No reason is given.
- Accept, **then** close with 4401 or 4429: the browser's `onclose` gets `event.code === 4401`.
- Channels' test client reports the code in both cases, so the test asserts the handshake *succeeded* first.

## Important code walkthrough

### `chats/views.py`, `?after=`
```python
after = self.request.query_params.get('after')
if after is None:
    return messages.order_by('-created_at')
try:
    after = int(after)
except ValueError:
    after = -1
if after < 0:
    raise ValidationError({'after': 'Must be a message id.'})
return messages.filter(id__gt=after).order_by('id')
```
- **No `after`:** the old behaviour, unchanged, newest first for the chat window.
- **`int()` in a `try`:** `'abc'` and `'1.5'` raise `ValueError`, and we turn that into a 400. Negative ids are
  refused too. One error message covers both cases.
- **`order_by('id')`, oldest first:** the client appends in order, so no reversing is needed.
- **Paginated (50) like the rest:** if more than 50 were missed, `next` is set, and the client reloads the chat instead.
- **Still `self.get_chat()` first:** someone outside the chat gets 404, as before.

### `chats/consumers.py`, `refuse()`
```python
async def refuse(self, code):
    self.refused = True
    await self.accept()
    await self.close(code=code)

async def receive(self, text_data=None, bytes_data=None):
    if getattr(self, 'refused', False):
        return  # a frame that got in before our close
```
- Between `accept()` and the client receiving the close, the client can still send a frame. A refused socket
  never got a rate-limit bucket, so without the check `receive()` crashed with
  `AttributeError: 'InboxConsumer' object has no attribute 'bucket'`. I removed the check on purpose, and
  `test_a_frame_sent_to_a_refused_socket_is_ignored` failed with exactly that error.

### `assets/app.js`, reconnect
```js
ws.onopen = () => {
  const reconnected = state.retry > 0;
  state.retry = 0;
  if (reconnected) {
    if (state.activeId) catchUp(state.activeId);
    loadChats();
  }
  ...
};
```
- **`state.retry > 0` means "this is a reconnect".** The first connection after login has `retry === 0`, so it
  doesn't make extra requests.
- **`catchUp`** fetches `?after=<largest id shown>`. If the user switched chats while it waited, it drops the
  result. `appendMessage` already skips ids it has shown, so a message that came by socket *and* by fetch appears once.

```js
const reconnectLater = () => {
  const delay = Math.random() * Math.min(1000 * 2 ** state.retry++, 15000);
  setTimeout(() => { if (state.me) connectInbox(); }, delay);
};
if (event.code === 4401) {
  refreshAccess().then((ok) => (ok ? reconnectLater() : logout()));
  return;
}
reconnectLater();
```
- **Why the 4401 path uses the backoff too:** before COR-5 was fixed, this branch never ran. Now it does. If a
  refreshed token were also refused, "reconnect at once" would be a tight loop. With the backoff, it slows down
  each time, and `retry++` also tells `onopen` to catch up.

## Problems we encountered
- [P-16 · Our WebSocket close codes never reached the browser (COR-5)](../problems-and-solutions.md#p-16--our-websocket-close-codes-never-reached-the-browser-cor-5)
- **Misplaced tests from T-04:** found because the new test "didn't exist" when run by name in `MessagingTests`.
  New GOTCHA rule: after inserting a class, list the classes and tests to check.
- **`timeout` doesn't exist on macOS.** My loop `timeout 40 python manage.py test …` printed nothing, because the
  command was never found, not because the tests hung. New GOTCHA rule.
- **The full suite hung once** (more than 5 minutes) while the new refusal tests were failing. Each test alone
  finished in under a second, and once the fix was in, the full suite took 1.4 s. **Root cause unknown.**
  *Hypothesis:* a `WebsocketCommunicator` left open by a failing assertion (before `disconnect()`) blocked a later
  test. I didn't reproduce it.

## Engineering decisions and trade-offs
- **Gap fetch, not a durable queue:** Decision 0.3. Postgres already answers "what did I miss?" with one query.
- **Reuse the pagination (50) instead of a separate limit of 200:** one code path. More than 50 missed messages
  is rare, and reloading the chat is then the simplest correct answer.
- **"Connected" means the first frame from the server, not `onopen`.** Once refused sockets are accepted first,
  `onopen` no longer proves anything. A ping on open guarantees a frame comes back on a socket that's really in.
- **Refuse with accept-then-close for 4429 too,** not only 4401. Same bug, same fix. (Session 010 said browsers
  would see 1006 for 4429. That was true then; it isn't now.)
- **Reload the sidebar on every reconnect:** the unread counts and previews were also stale. One extra request,
  spread out by the jitter.

## What I should remember
- The live stream can lose things. The database is the truth. Fetch the gap after reconnecting.
- Use a growing id as the cursor, not a timestamp.
- Every retry goes through a jittered backoff, including special cases.
- In Channels, accept and then close, or the browser never sees your code.
- When a fix makes dead code reachable (the 4401 branch), review that code as if it were new.
- Run the real thing. The browser check found two bugs that 72 green tests didn't.

## Review questions
1. Why can't the channel layer replay the messages a socket missed?
2. Why is `?after=<id>` better than `?since=<timestamp>`?
3. Code reading: why does `catchUp` check `chatId !== state.activeId` after the `await`?
4. 10,000 clients reconnect after a deploy. Roughly how does full jitter change the arrival pattern, compared
   with a fixed 1 s, 2 s, 4 s… backoff?
5. Why did the existing test `test_missing_or_invalid_tokens_are_refused` pass for months, even though browsers
   never saw 4401?
6. Debugging: a user says "after my laptop wakes up, my old messages show twice". What would you check first?

<details><summary>Answer key</summary>

1. It's at-most-once: it delivers to sockets that exist right now and stores nothing for a socket that's gone.
   It also drops queued notifications after 60 s or 100 pending.
2. Ids are unique and only grow. Timestamps can be equal, so a "since" query can skip or repeat messages at the boundary.
3. The fetch takes time. If the user opened another chat meanwhile, appending these messages would put them in
   the wrong conversation.
4. With a fixed backoff, all 10,000 arrive in the same instant at 1 s, again at 2 s, and so on: spikes. With full
   jitter, they're spread evenly over each window (for example, about 10,000 over 0–1 s), so the server sees a
   steady rate instead of a wall.
5. Channels' test client reports the close code even when the close comes before the handshake. The test checked
   the code, not that the handshake succeeded, so it couldn't see what a browser sees.
6. The de-duplication: `appendMessage` skips ids already in `state.seenIds`. Check that the same message
   really has the same id, of the same type, on both paths (socket and fetch). A string `"42"` and a number `42`
   are different keys in a `Set`. Then check that `catchUp` sent the right `after`.
</details>

## Next steps
- Review and merge the T-09 PR.
- Stage 0 code tasks in the suggested order are now done (T-01, T-08, T-11, T-02, T-03, T-04, T-09). What's left
  of Stage 0 is the **baseline load test** with the realistic profile, from a second machine.
