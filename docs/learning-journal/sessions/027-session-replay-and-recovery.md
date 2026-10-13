# 027 · Four gaps Codex reproduced: replay after logout, double send, catch-up gap, load-test receipts

- **Date:** 2026-10-12 · **Phase:** Stage 0
- **Task:** four findings Codex reproduced at `1abe93c` (not part of the audit checklist) · **Branch:**
  `fix-session-replay-and-recovery`, stacked on `fix-api-contract-and-browser-skips` (PR #35), so merge #35 first
- **Files:** `assets/app.js`, `loadtest/run.py`, `chats/test_browser.py`, `loadtest/test_run.py`, docs
- **Objective:** a request from before logout never acts for the next account; a message is never sent twice
  while its fate is checked; no gap between the history and the socket; load-test receipts are accepted.

## Before we started
- PR #34 was merged; PR #35 was open and touches `chats/test_browser.py` and the same docs, so this branch is
  stacked on it.
- Codex is fixing the PR #34 review findings on its own branch (`fix-pr34-followups`), in `loadChats()` and
  `accounts/signals.py`. This work stays out of both.

## What we accomplished
1. **Tests first.** 4 new tests, each failing on the old code for its own reason:
   - **High (browser):** account 1's `PATCH /auth/profile/` is held; account 1 logs out and account 3 logs in; the held
     request is answered 401. The old code refreshed with account 3's token and sent the PATCH again:
     `2 != 1 : the request was sent again`.
   - **Medium (browser):** echoes dropped; after the 10 s timeout the history check (`?after=`) is held and Enter is
     pressed: `2 != 1` messages in the database.
   - **Medium (browser):** the history request is held and its answer taken from the server (`route.fetch()`); then
     the socket is closed, a message is saved while no socket listens, and the socket reconnects before the
     history is delivered. Old code: 1 row (`before`), not 2.
   - **Medium (load tester):** a fake socket delivers one message with id 41; the receipt sent back was
     `{'action': 'read', 'chat_id': 7}`, with no `up_to`.
2. **Fixes:**
   - `api()`: `if (session !== state.session) return dropped();` right after `fetch`, before the 401 → refresh →
     retry step. The check after reading the body stays (logout can happen during that too).
   - The send's timeout handler awaits `reconcileSend(sent)` and only then settles, if the send is still the
     pending one. A late echo, logout or a dead socket still settle it sooner.
   - `catchUp()` with no boundary yet sets `state.catchUpDue`; `openChat()` resets it, and runs the catch-up after
     the history if it's set.
   - `loadtest/run.py`: the receipt carries `'up_to': data.get('id')`.
3. **The load tester against a real server** (Daphne, 40 seeded users, all active, 12 messages/min, 20 s):

   | `run.py` | Messages | `server_errors` | Verdict |
   |---|---|---|---|
   | old | 167 | **169** | OK |
   | new | 168 | **0** | OK |

   The seeded users were deleted afterwards (`loadtest_seed --delete`), and the tokens file was in `/tmp`.
4. **Results:** the 3 new browser tests passed 3 runs in a row. `make test` → **147 run, OK (12 skipped)**. Real
   Postgres + Redis with `REQUIRE_BROWSER_TESTS=True` → **175 tests, OK**. `ruff check .` clean.
   `makemigrations --check`: no changes.

**Not done:**
- **The load-test verdict ignores `server_errors`.** The old run had 169 error frames and still said OK. Found here,
  not fixed (it's a change to how a run is judged; see Next steps).
- **The load-tester tests skip in CI** (`aiohttp` isn't installed in the CI jobs), so the new receipt test runs
  only locally.

## Concepts I learned
- [Reliable delivery and reconnects](../concepts/reliable-delivery-and-reconnects.md): new notes on checking the
  session before acting, pending-until-settled, and snapshot vs subscription.
- [Testing and CI](../concepts/testing-and-ci.md): `route.fetch()` + `route.fulfill(response=...)`.

### Snapshot vs subscription
- **Simple definition:** a *snapshot* is "everything up to now" (one request); a *subscription* is "everything from
  now on" (the socket). If the subscription starts after the snapshot was taken, whatever happened in between is in
  neither.
- **Everyday example:** you photocopy a notice board at 9:00 and start watching it at 9:05. A note pinned at 9:02 is
  on neither the copy nor what you've watched. Look at the board once more after you start watching.
- **Here:** that "once more" is the catch-up (`?after=syncedUpTo`); it needs the snapshot's boundary, so it waits
  for the history instead of giving up.

## Important code walkthrough

### `assets/app.js`: `api()`
```js
const res = await fetch(API + path, { ... });
if (session !== state.session) return dropped();
if (res.status === 401 && retry && await refreshAccess()) {
  return api(path, { method, body, isForm, retry: false });
}
```
- `refreshAccess()` uses `state.refresh`, which after a new login is the **new** account's. So a 401 that belongs
  to the old session must never reach it.

### `assets/app.js`: the send stays pending
```js
state.ackTimer = setTimeout(async () => {
  if (state.sending !== sent) return;
  await reconcileSend(sent);
  if (state.sending === sent) settleSend();
}, ACK_TIMEOUT_MS);
```
- If the history check never answers, the 70 s liveness check closes the socket and calls `settleSend()`, so
  sending can't stay locked forever (the H-06 rule: no wait without a deadline).

### `assets/app.js`: a catch-up that waits
```js
if (state.syncedUpTo === null) { state.catchUpDue = true; return; }
...
if (!await loadHistory(chatId)) return;
scrollToBottom();
if (state.catchUpDue) { state.catchUpDue = false; catchUp(chatId); }
```
- `openChat()` resets the flag first: a socket that was ready *before* the history request subscribed before the
  snapshot, so there's no gap to fill.

## Problems we encountered
- [P-34 · A late answer acted for the wrong account, sent twice, or left a gap](../problems-and-solutions.md#p-34--a-late-answer-acted-for-the-wrong-account-sent-twice-or-left-a-gap)
- **Making the gap test deterministic.** Holding the history request and releasing it later lets the server take
  its snapshot *after* the gap message, so the bug can't show. `route.fetch()` takes the server's answer at the
  moment we choose, and `route.fulfill(response=...)` delivers it later.

## Engineering decisions and trade-offs
- **A flag, not "always catch up after the history":** the extra request runs only when the socket became ready
  during the load, which is the only time there can be a gap.
- **Keep the send pending rather than disable the composer:** one rule (`state.sending`) already blocks sending;
  extending how long it lasts is a one-line change.

## What I should remember
- Check "is this still the same session?" before *acting* on an answer, not just before drawing it.
- A message is "in flight" until something proves its fate. Don't unlock early.
- Snapshot + subscription needs a look-again after the subscription starts.
- When a protocol field becomes required, update every client: the browser, the tests and the load tester.

## Review questions
1. Account A's request gets a 401 after B signs in. Under the old code, whose token did the retry use, and why?
2. Why wasn't the session check after `res.text()` enough?
3. After a lost echo, why could Enter send the message twice?
4. What stops the send from staying pending forever if the history check hangs?
5. The socket is ready while the history loads. Which message can be missing, and why?
6. Why does `openChat()` reset `catchUpDue` before loading?
7. The old load-test run had 169 server errors. Why did it still say OK?

<details><summary>Answer key</summary>

1. B's. `refreshAccess()` reads `state.refresh`, which B's login had replaced, then `api()` resent the request with
   the new access token.
2. It runs after the refresh-and-retry step. The retry had already been sent as B; the check only stopped A's
   *answer* from being used.
3. The timeout set `state.sending` to null before the history check started, and the text was still in the
   composer. Enter saw nothing in flight and sent it.
4. The liveness check: every 30 s it looks for a frame in the last 40 s; if there was none, it closes the socket
   (within about 70 s) and calls `settleSend()`. Logout and a late echo
   also settle it.
5. One saved after the history's snapshot but before the socket subscribed: not in the history, never sent live.
   The catch-up that would find it returned early (no boundary yet) and was never retried.
6. Only a socket that becomes ready *during* this load can have subscribed after the snapshot. A flag left over
   from an earlier chat or connection would trigger a needless request.
7. The verdict (`loadtest/verdict.py`) doesn't look at `server_errors` at all.
</details>

## Next steps
- Merge PR #35, then this PR.
- Make the load-test verdict count `server_errors` (and decide the limit), and install `aiohttp` in a CI job so the
  load-tester tests run there.
- The audit risks R-01…R-07.
