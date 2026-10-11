# 016 · Codex review: four frontend bugs, and the first browser tests

- **Date:** 2026-10-11 · **Phase:** Stage 0
- **Task:** findings #3–#6 from the Codex review (session 015), not in the backlog · **Branch:** `fix-frontend-chat-bugs`
- **Files:** `assets/app.js`, `templates/index.html`, `chats/test_browser.py` (new), `requirements.in`, `requirements.txt`,
  `.github/workflows/tests.yml`, docs
- **Objective:** fix the four `app.js` bugs, with tests in a real browser that fail before and pass after.

## Before we started
- PR #25 (findings #1–#2) merged as `6699066`. Branched `fix-frontend-chat-bugs` from the updated `main`.
- `app.js` had **no tests**. You chose Playwright browser tests ([decision 004](../decisions/004-browser-tests-with-playwright.md)).

## What we accomplished
1. **Added Playwright:** `playwright` in `requirements.in`, compiled with Python 3.13 (added `playwright 1.63.0`,
   `greenlet`, `pyee`; no other pin changed). CI's `test-postgres-redis` job now installs Chromium.
2. **Wrote 6 browser tests first** (`chats/test_browser.py`). Against the old `app.js`, 5 failed:
   - switching chats: `['from B', 'from A']`, so A's message was drawn in B;
   - load older: `['m03', 'm02', 'm01', 'm04', …]`;
   - "Show more chats": no such button; lookup of a chat beyond the first 50: nothing opened;
   - blocked send: the composer was empty.
   - The 6th, "a delivered message clears the composer", passed. It guards the normal path while #6 changes it.
3. **Fixed `app.js`** (details below). All 6 pass.
4. **Results:** real Postgres + Redis (`python manage.py test`) → **89 tests, OK**. `make test` (SQLite) → OK, with
   the 6 browser tests skipped (they need Postgres and Redis). `ruff check .` (0.16.10) → clean. `node --check assets/app.js` → OK.

**Not done:**
- **Not looked at by a person in a browser.** Only the tests have checked it, so the "Show more chats" button's look
  is unchecked. Have a look with `make run`.
- Chats beyond page 1 keep the online dot they had when loaded; the 45 s poll refreshes only page 1.
- If the socket drops while a message is waiting, the text stays in the composer even if the message did arrive.
  Sending it again would make a duplicate. Fixing that needs a message id chosen by the client.
- Only one message can be waiting at a time. Enter does nothing until the server answers (usually milliseconds).
- Codex #7–#9 are still open, and Codex's "reconnect recovery" browser test isn't written.

## Concepts I learned

### Stale responses (a race condition)
- **Simple definition:** you ask for X, then change your mind and ask for Y. If X's answer arrives *after* Y's, and the
  code doesn't check, X's answer overwrites what you're looking at.
- **Why it happens in JS:** `await` pauses a function, and other code (another click) runs meanwhile. When the
  function continues, the world may have changed.
- **Fix:** remember "which request is current" before `await`, and compare after. We use a counter, `state.opened`.
  Comparing the chat id alone fails for A → B → A, where A's *first* answer would pass the check.

### Optimistic vs confirmed UI
- **Optimistic:** act as if it worked (clear the box now) and fix things up if it fails. Feels fast, but here
  nothing fixed it up, so the text was lost.
- **Confirmed:** wait for the server. We wait for our own message's **echo**. The server sends every message to both
  people, sender included, so the echo means "saved".

### Pagination on the client
- The API pages lists, 50 per page (`PAGE_SIZE`). `data.next` is the URL of the next page, or `null`. Ignoring it
  silently hides everything after the first page.

## Important code walkthrough

### Dropping stale answers (`assets/app.js`)
```js
async function loadHistory(chatId, page = 1) {
  const opened = state.opened;
  const data = await api(`/chats/${chatId}/messages/?page=${page}`);
  if (opened !== state.opened) return null;
```
- `openChat` and the back button do `state.opened += 1`. An answer that started under an older value is ignored.
- `openChat` returns early on `null`, so it also skips `sendRead`: no read receipt for a chat that never reached the screen.

### The order of older pages
```js
const ordered = page > 1 ? data.results : [...data.results].reverse();
for (const msg of ordered) appendMessage(msg, { prepend: page > 1 });
```
- The API gives newest first: `[50, 49, …, 1]`. **Appending** needs oldest first, so page 1 is reversed.
- **Prepending** one at a time puts each message *above* the previous one. So feed it newest first: 50, then 49
  above it, …, then 1 at the top. The old code reversed here too, and the double reversal gave `3, 2, 1`.

### Keeping the draft
```js
state.sending = { chatId: state.activeId, text };   // on submit, instead of clearing
...
if (isOurSend(data)) { /* clear the composer */ state.sending = null; }   // our echo arrived
...
state.sending = null;   // on an error frame, or when the socket closes: the text stays
```
- Error frames don't say which frame they answer, so any error while a send is waiting counts as that send failing.

## Problems we encountered
- [P-21 · Four frontend bugs, with no tests to catch them](../problems-and-solutions.md#p-21--four-frontend-bugs-with-no-tests-to-catch-them)
- **The route handler crashed the first run:** `page.route(url, held.append)` errored inside Playwright, which
  inspects the handler's arguments. `lambda route: held.append(route)` works. (Root cause not traced: *Hypothesis*.)
- [P-22 · Browser tests passed on the Mac but never connected in CI](../problems-and-solutions.md#p-22--browser-tests-passed-on-the-mac-but-never-connected-in-ci):
  the first CI run failed all 6 browser tests. Linux forks the server process, macOS spawns it. Fixed by forcing spawn;
  with fork forced as the default locally, 89 OK.
- **A test run printed nothing:** I had used `timeout 600 python …`, and macOS has no `timeout` command. That's
  already in GOTCHA.md.

## Engineering decisions and trade-offs
- **A counter instead of cancelling the request** (`AbortController`): the browser may still finish a cancelled
  request, so the check is needed anyway. The counter is one line per place.
- **"Show more chats" button instead of loading every page:** loading all pages on every 45 s poll would send
  N requests per user. A button costs nothing until used.
- **Waiting for the echo instead of adding message ids to the protocol:** no server change. The id is the better
  long-term fix (it also solves duplicates after a reconnect), and is listed under "Not done".

## What I should remember
- After an `await`, re-check that the answer still matters before using it.
- Two reversals cancel out. When order looks wrong, write the list down at each step.
- `results` without `next` is a bug as soon as there's a second page.
- Don't throw away user input until the server has accepted it.
- Make timing bugs happen on purpose in tests (hold the request) instead of hoping for them.

## Review questions
1. In the chat-switch bug, why did comparing `chatId !== state.activeId` (as `catchUp` does) not fully fix it?
2. Trace the old "load older" code for the list `[3, 2, 1]` (newest first). What ends up on screen, and why?
3. Why does `openChat` return before `sendRead` when the history answer is stale?
4. What tells the client that its message was saved, given the server sends no "ok" frame?
5. Why do the browser tests skip on `make test`?
6. Why did the browser tests pass on the Mac but fail in CI?
7. Code reading: in `loadChats`, why keep `state.chats` entries that page 1 doesn't include?

<details><summary>Answer key</summary>

1. It fails for A → B → A. The first request for A finishes while A is open again, so the check passes and its
   answer is drawn, possibly with gaps. A counter changes on every open, so the old answer never matches.
2. Reversed to `[1, 2, 3]`, then each prepended: 1; then 2 above it; then 3 above that. Screen shows 3, 2, 1.
3. Otherwise the app sends a read receipt for chat A after the user moved to B. A's messages would be marked
   read, and the sender would see ✓✓, though nobody saw them.
4. Its own message coming back over the socket (the echo). The server sends each new message to both participants'
   groups, including the sender's.
5. `ChannelsLiveServerTestCase` runs the server in another process. That process can't see an in-memory SQLite
   database or the test's fake Redis, so the tests need real Postgres and Redis.
6. Linux starts the server process with fork (a copy of the test process and its state); macOS uses spawn
   (a fresh Python). The forked server never accepted the socket. The test now forces spawn everywhere.
7. Those are older pages the user loaded with "Show more chats". The poll fetches only page 1. Replacing the
   whole list would drop them every 45 seconds.
</details>

## Next steps
- Look at the app in a browser, then review and merge this PR.
- Codex #8: fix the load tester, then rerun the baseline (session 014's numbers are unconfirmed until then).
- Codex #7 (24 h group expiry) and #9 (REST read receipts).
