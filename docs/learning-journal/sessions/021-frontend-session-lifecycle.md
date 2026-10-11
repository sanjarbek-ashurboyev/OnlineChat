# 021 · Codex audit: the frontend's session lifecycle

- **Date:** 2026-10-11 · **Phase:** Stage 0
- **Task:** findings H-04, H-06, M-12 and L-03 from [Codex's second audit](../../scaling/05-codex-audit-2026-10-11.md)
  · **Branch:** `fix-frontend-session-lifecycle`
- **Files:** `assets/app.js`, `chats/test_browser.py`, docs
- **Objective:** nothing from before logout leaks into the next session; a lost echo or a dead connection never
  blocks sending for good; a network blip at startup or reconnect doesn't leave the app disconnected or signed out;
  rate-limit errors say what really happened.

## Before we started
- PR #30 merged (`6f264b6`). Branched `fix-frontend-session-lifecycle` from the updated `main`.
- Checked Playwright 1.63 has `page.route_web_socket` (sit between the page and the server and drop chosen frames)
  and `page.clock` (fake timers we can fast-forward). Without them, H-06 and the liveness check could only be tested by
  waiting for real.

## What we accomplished
1. **Wrote 10 browser tests first** (`SessionLifecycleTests`). On the old `app.js` **all 10 failed**, each at the
   assertion for its bug:
   - H-04: the refresh finished after logout and put an access token back; User 2's chat appeared in the next
     account's list; the next account's first message never reached the server.
   - H-06: with echoes dropped, the saved message never showed; with sends dropped, no error ever appeared; with
     pongs dropped, no new connection was ever made.
   - M-12: with the chat list failing once, the socket never connected; a network error loading the profile signed
     the user out; a network error during the 4401 refresh left the page disconnected for good.
   - L-03: a throttled login said "Too many searches. Try again later."
2. **H-04:** `state.session` is bumped by `logout()`. `api()` and `refreshAccess()` note it when they start, and an
   answer for an older session returns `dropped()`, a promise that never settles, so nothing after it runs. `logout()`
   also cancels the reconnect and startup timers, detaches all socket handlers, and clears the pending send, open chat,
   message rows, composer, and lookup and send errors.
3. **H-06:** after 10 s without an echo, `reconcileSend()` fetches the history after the last message shown. If our
   message is there, it's drawn and the composer cleared; if not, the text stays and the page says it may not have
   been sent ([decision 007](../decisions/007-lost-echo-check-the-history.md)). Separately, if no frame at all
   arrived for 40 s, the ping timer treats the socket as dead and reconnects.
4. **M-12:** `start()` opens the socket without waiting for the chat list (the 45 s poll retries the list). Startup
   signs out only on a 401 (the server refused the tokens, even after a refresh); otherwise it shows "Can't reach the
   server. Trying again…" and retries in 5 s. `refreshAccess()` now returns `false` only when the server refuses the
   refresh token, and throws on network or server errors; the 4401 path then retries instead of stalling.
5. **L-03:** removed the special 429 text. DRF's own message ("Request was throttled. Expected available in 42
   seconds.") is shown instead.
6. **Results:**
   - `python manage.py test chats.test_browser` → **16 tests, OK**, run twice in a row (about 43 s each).
   - `make test` → **112 run, OK (9 skipped)**. Real Postgres + Redis → **128 tests, OK**. `ruff check .` → clean.
     `node --check assets/app.js` → OK.

**Not done:**
- No idempotency key: a message sent twice with the same text inside 10 s can confuse the history check (decision 007).
- The liveness check takes up to about 70 s to notice a dead connection (the next ping tick after 40 s of silence).
- The rest of the frontend findings (M-03, M-08, M-09, M-10, M-13) belong to the "message consistency" PR.

## Concepts I learned

### Session generations
- **Simple definition:** a counter that changes whenever "who is signed in" changes. Async work remembers the value
  it started with and gives up if it changed.
- **Everyday example:** a restaurant ticket number. If your order comes out after you've left and someone else sat
  down, the waiter checks the ticket and doesn't give them your food.
- **Here:** `state.session`, checked in `api()` and `refreshAccess()`, the two places every network answer passes.

### A promise that never settles
- `new Promise(() => {})` never resolves or rejects, so code after `await` on it never runs, and no error appears.
  It's garbage-collected once nothing references it. We use it to drop answers for an old session quietly.

### Deadlines for every wait
- Waiting for the echo, the pong, or the server at startup each got a deadline and a plan for when it passes.

### Fake clocks in browser tests
- `page.clock.install()` replaces `setTimeout`, `setInterval` and `Date` in the page. `fast_forward(11_000)` runs
  every timer due in the next 11 s at once, so a 10-second timeout is tested in milliseconds.

## Important code walkthrough

### `assets/app.js`: dropping stale answers in `api()`
```js
async function api(path, { method = 'GET', body, isForm = false, retry = true } = {}) {
  const session = state.session;
  ...
  const text = await res.text();
  if (session !== state.session) return dropped();   // an answer for whoever was signed in before
```
- One check covers every caller (`loadChats`, `loadHistory`, lookup, profile…), because they all go through `api()`.

### `assets/app.js`: waiting for the echo, with a deadline
```js
const sent = { chatId: state.activeId, text, after: Math.max(0, ...state.seenIds) };
state.sending = sent;
state.ackTimer = setTimeout(() => {
  if (state.sending !== sent) return;
  settleSend();
  reconcileSend(sent);
}, ACK_TIMEOUT_MS);
```
- `after` is the newest message shown when we sent, so the history check only fetches what came after it.
- `settleSend()` clears both `state.sending` and the timer; the echo, an error frame, a close and logout all call it.

### `chats/test_browser.py`: dropping our echo between page and server
```python
def drop_echoes(ws):
    server = ws.connect_to_server()
    ws.on_message(server.send)
    server.on_message(lambda frame: None if is_message_frame(frame) else ws.send(frame))
```
- Frames from the page go to the server unchanged; `message` frames coming back are swallowed. The message is saved,
  but the page never hears about it, exactly the H-06 situation.

## Problems we encountered
- [P-29 · Logout didn't stop the previous session's work](../problems-and-solutions.md#p-29--logout-didnt-stop-the-previous-sessions-work)
- **My first run hung for 400 s.** `page.evaluate('loadChats()')` returns a promise, and Playwright waits for it,
  but the test was holding that request and would only release it later. Deadlock. Fixed with `void loadChats()`.
- **`page.route(..., held.append)` failed:** Playwright can't use a built-in method as a handler. Wrapped it in a lambda.
- I ran the new tests one by one (a scratch script with a 90 s timeout each), so a hang shows which test it is.

## Engineering decisions and trade-offs
- [Decision 007](../decisions/007-lost-echo-check-the-history.md): check the history rather than add idempotency keys.
- **Drop stale answers with a never-settling promise** rather than throwing a "stale" error: a thrown error would show
  up in the callers' `catch` blocks (lookup and profile show error text) and in the console.
- **Liveness on the existing ping timer** rather than a separate pong timer: no new timer, at the cost of noticing
  later (about 70 s at most).

## What I should remember
- Every async answer must still belong to the current session when it arrives.
- Every wait needs a deadline; every deadline needs a recovery plan.
- Sign out only when the server says the credentials are bad. Retry everything else.
- `page.evaluate` waits for a returned promise; `void` it when the test is holding its request.

## Review questions
1. How could a token refresh sign a user back in after they pressed "Log out"?
2. Why check the session in `api()` and `refreshAccess()` instead of in `loadChats()`, `loadHistory()` and the others?
3. After 10 s without an echo, the page fetches the history. What are the two possible outcomes and what does each do?
4. Why must a network error during startup not call `logout()`?
5. How does the test for H-06 make the server save a message but keep its echo from the page?
6. What does `page.clock.fast_forward(11_000)` do, and why is it better than `wait_for_timeout(11_000)`?

<details><summary>Answer key</summary>

1. The refresh request started before logout (from a 401). Its answer arrived after logout, and `refreshAccess()`
   called `saveTokens()`, writing a fresh access token to `localStorage`. The next page load would sign in.
2. Every network answer passes through those two functions, so one check covers all callers, including ones added
   later.
3. Our message is there: it was saved and only the echo was lost, so draw it and clear the composer. It isn't there:
   keep the text and show "may not have been sent".
4. `logout()` deletes the tokens. A blip in the network would then force the user to type their password again,
   although their tokens were fine. Only a 401 proves the tokens are bad.
5. `page.route_web_socket` puts the test between page and server: frames from the page are forwarded, frames of type
   `message` from the server are dropped.
6. It runs every timer due in the next 11 s immediately, so the test takes milliseconds and isn't affected by a slow
   machine. `wait_for_timeout` would really wait 11 s.
</details>

## Next steps
- Review and merge this PR.
- Next audit group: message consistency (M-03, M-04, M-06, M-07, M-08, M-09, M-10, M-11). It's the largest and has
  real design choices (sync boundary, cursor pagination).
