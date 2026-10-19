# 043 · F-05: messages (wallpaper, tails, days, ticks, ↓, load on scroll, "Not delivered")

- **Date:** 2026-10-19 · **Phase:** Frontend redesign, Phase 1
- **Task:** F-05 in the [frontend plan](../../frontend/plan.md) · **Branch:** `f-05-messages`
- **Files:** `assets/js/messages.js`, `assets/js/composer.js`, `assets/js/socket.js`, `assets/js/format.js`,
  `assets/wallpaper.svg` (new), `assets/app.css`, `templates/index.html`, `chats/test_browser.py`, `GOTCHA.md`, docs
- **Objective:** the conversation itself looks and behaves like a messenger: a wallpaper, bubbles with tails in runs,
  "Today" / "Yesterday" between days, ticks drawn as icons, a ↓ button, older messages that load as you scroll up, and
  a message that didn't go through says so on its bubble and can be sent again.

## What was done
1. **Tests first.** 5 new browser tests (`MessageViewTests`) and 4 changed ones (below). On the F-04 code, 9 of the
   11 failed (the other 2 still pass, as they should: one is unchanged, and the Enter test still guards against
   sending twice). New:
   - messages are split by day: a divider with the date, then "Yesterday", then "Today", each before its first
     message; a live message today adds no second "Today";
   - a run from one sender is grouped: `[a, b, c]`, `[d]` (ours), `[e]` (10 minutes later, a new run); the last of a
     run gets the tail;
   - ticks are icons with a name: "Read" and "Sent";
   - the ↓ button appears when you scroll up, counts a message that arrives below ("1"), takes you down, and goes;
   - a message that wasn't delivered: its bubble shows at once with a clock and the composer empties; with no echo
     and nothing in the history it says "Not delivered", the text is back in the composer; "Send again" sends it
     once, and the real message takes the bubble's place.
2. **Wallpaper** (`assets/wallpaper.svg`): 13 doodles drawn for this app (speech bubble, heart, star, paper plane,
   smile, note, cloud, sparkle, moon, dots), used as a CSS **mask** over a soft gradient, so each theme paints them in
   its own colour. It doesn't scroll. "Increase contrast" turns the pattern off.
3. **Days and runs:** `decorate()` walks the rows after every change and puts a divider before the first message of
   each day, and `group-start` / `group-end` on runs (same sender, same day, less than 5 minutes apart). Runs sit 2 px
   apart; the corners where bubbles of a run meet are tighter; the last one has a tail (a small SVG mask in the
   bubble's own colour; the shadow is a `drop-shadow` so it follows the tail).
4. **Time and ticks inline:** `.meta` floats right, into the last line when there is room, else onto its own line.
   Ticks are SVG icons (`#i-check`, `#i-check2`, `#i-clock`) with `role="img"` and a name; the row's `data-status` says
   `sending`, `sent`, `read` or `failed`.
5. **↓ button** (`#to-bottom`): over the messages, above the composer; it grows in once you're 200 px up, shows how
   many messages arrived below, and scrolls down smoothly (at once with "Reduce motion").
6. **Load on scroll:** within 400 px of the top, the next older page loads; the message you were reading stays exactly
   where it was (`scrollTop += added height`, with the browser's own scroll anchoring switched off). "Load older
   messages" appears only if a page failed, to try again.
7. **Optimistic sending** (`sendText`, `failSend` in `composer.js`; `showSending`, `showNotDelivered` in
   `messages.js`): the bubble is drawn at once; the echo, the history check, or the catch-up replaces it with the real
   message. A refusal (error frame), no answer (history check) or a dropped socket makes it "Not delivered": a red "!"
   beside it sends it again, and the text goes back into the composer if that's empty. `#send-error` still says why.
8. **Contrast** (checked with a script, worst case over the wallpaper): date pills ≥ 5.41:1 (light) and ≥ 10.66:1
   (dark); "Not delivered" on our bubble 5.08 / 4.81; white "!" on red 5.62.
9. **Tests changed on purpose** (and the plan's hook list):
   - the 3 tick checks read the row's `data-status` instead of `✓✓` in `.meta` (ticks are icons now);
   - `HistoryTests` scrolls to the top instead of clicking, and now also checks the reading position and that there
     is one "Today", not one per page;
   - the failed-older-page test scrolls up, then retries with the button;
   - the "Enter during the history check" test types the text again before Enter (the composer empties on send now);
   - the lost-echo test waits until the saved message has replaced its bubble (the text is on screen from the start).
10. **A flaky F-04 test found and fixed** (P-48, below): `ChatRowTests` now waits for both start-up chat-list loads and
    saves its messages before delivering them.
11. **Screenshots** (throwaway database, dropped afterwards) in `docs/frontend/screenshots/f-05/`: desktop chat light
    and dark, the wallpaper with "Pick a conversation", phone chat light and dark, the ↓ button with a count, and
    "Not delivered" light and dark.
12. **Results:** `make test` **177 run, OK (skipped=23)** (240 found). Real Postgres + Redis with
    `REQUIRE_BROWSER_TESTS=True`: **240 run, OK**, twice (a minute apart), no `Too Many Requests` (after the P-48
    fix; the run before it had the 1 failure described there). `ChatRowTests` 5 runs in a row: OK. Ruff 0.16.10: all checks passed. ESLint
    (`no-undef`, `no-unused-vars`): clean.

**Not done:**
- **One message on its way at a time** (as before). Pressing Enter on a second message while the first has no answer
  yet does nothing; the text stays in the composer. Usually that window is a few milliseconds; after a lost echo it
  is up to 10 s.
- One "Not delivered" bubble at a time: a new send replaces an older failed one (its text was put back in the
  composer).
- No spinner while an older page loads (it's usually quick).
- A "Not delivered" bubble is lost if you switch chats (the text stays in the composer, as before).
- "Today" turns into "Yesterday" only when the list is redrawn, not at midnight by itself.
- No backend change was needed.

## Concepts

### Optimistic UI
- **Simple definition:** show the result of an action before the server confirms it, marked as pending, and fix it
  when the answer comes.
- **Example:** the clock on a bubble you just sent, replaced by one tick when the server's echo arrives.
- Guide: [interface design](../concepts/interface-design.md#optimistic-sending-show-it-now-confirm-it-later-f-05).

### CSS masks
- **Simple definition:** a picture used as a stencil: where it is opaque, the element shows; elsewhere it's cut away.
- **Example:** the wallpaper is a colour, stencilled by `wallpaper.svg`; change the colour and the doodles change
  with it. The bubble's tail is the bubble's colour stencilled by a small curve.

### Floats for inline time
- **Simple definition:** `float: right` puts an element at the right of the current line if it fits there, else on
  the next one. That's exactly where a message's time goes.

## Walkthrough

`assets/js/messages.js`, where a real message meets its bubble:
```js
if (outbox && msg.sender_id === state.me.id && state.activeId === outbox.sent.chatId
    && msg.text === outbox.sent.text && msg.id > outbox.sent.after) {
  outbox.row.remove();
  outbox = null;
  clearComposerIf(msg.text);
}
```
- This sits in `appendMessage`, the one door every message comes through (history, live, catch-up), so the echo,
  the history check and a reconnect's catch-up all resolve the bubble the same way.
- `msg.id > outbox.sent.after`: an older message with the same text ("ok") can't be mistaken for this one.

`assets/js/composer.js`:
```js
const saved = await reconcileSend(sent);
if (state.sending === sent) (saved ? settleSend : failSend)();
```
After the `await`, check the send is still the one we were waiting for (GOTCHA: the user may have logged out or the
socket may have failed it meanwhile).

`assets/js/messages.js`, older pages:
```js
const before = box.scrollHeight;
...
box.scrollTop += box.scrollHeight - before;
```

## Problems
- **P-48: a browser test's fake message was undone by a chat-list load that answered late.** Root cause
  **Confirmed** by delaying the second start-up `/chats/` answer by 0.4 s in a throwaway test: the order went back to
  the server's. Fix in the tests; re-checked with the same delay. Details in
  [problems and solutions](../problems-and-solutions.md#p-48--a-browser-tests-fake-message-was-undone-by-a-chat-list-load-that-answered-late).
- **A hung test run left processes behind.** My first in-page version of that test waited for movement with no limit;
  when the movement never came it hung, and after I stopped it, its live-server process kept 3 sessions on
  `test_onlinechat` ("being accessed by other users" on the next run). I stopped those two processes (they were from
  that run). The loop now has a 120-frame limit.
- **The screenshot script hit the login limit** (several logins within a minute: "Request was throttled"). The script
  now waits and tries again.

## Decisions
- **Optimistic bubble, with the text also put back on failure.** Telegram only keeps it on the bubble; putting it back
  in an empty composer also keeps the old promise ("a message that fails keeps its text") and lets you edit it.
- **The real message always wins.** "Not delivered" after a dropped socket may be wrong; instead of guessing, any real
  copy that arrives later removes the bubble and the composer's copy.
- **Dividers and runs recomputed after every change** rather than patched per insert: messages arrive in any order,
  and one walk is simpler to get right.
- **The "Load older messages" button stays, only for retrying.** Load on scroll is the normal path; a failed page
  needs a visible way to try again.
- **Plain dividers, not sticky ones.** Sticky date pills in one container pile on top of each other (a wider pill
  peeks out from under a narrower one); doing it right means a container per day, which complicates the ordering
  code. Not worth it now.

## What I should remember
- Optimistic UI needs a way back: every pending state must end in "confirmed" or "failed", whichever way the answer
  comes.
- Content added above the reader must move the scroll position by exactly its height.
- A test that fakes server events must make the server agree, or wait for everything the server is still sending.
- Every "wait until" in a test needs a limit.

## Review questions
1. Why is the "Not delivered" bubble removed in `appendMessage`, and not in the socket's echo handler?
2. Why does `msg.id > outbox.sent.after` matter?
3. What would go wrong if `loadOlder` set `scrollTop = scrollHeight - before` (the old code) when you scroll up fast?
4. Why is the wallpaper a mask and not a background image with colours in it?
5. Why did the F-04 test fail only sometimes, and why was the app right?
6. Why does the test helper save the message to the database before sending the fake frame?

<details><summary>Answer key</summary>

1. Every message comes through `appendMessage`: the echo, the history check after a lost echo, and the catch-up after
   a reconnect. Removing it there resolves the bubble whichever way the real message arrives.
2. An older message of ours with the same text (say "ok") was already in the history; only a message newer than the
   send can be the one we sent.
3. That formula assumes you are at the very top. If you were 300 px down when the page arrived, you'd be thrown 300 px
   up. Adding the difference to where you are now keeps your place exactly.
4. A mask is only a shape; the colour comes from CSS. Light, dark and high-contrast modes then change one variable
   instead of needing three images.
5. Two chat-list loads start when the page opens; the test waited only for the socket. When the second load answered
   after the test's fake message, it brought the server's order, which didn't include that message. The app should
   trust the server: the message really didn't exist there.
6. So that any chat-list load that happens later agrees with what the test showed the page, as it would with a real
   message.
</details>

## Next steps
- **You:** on your phone, turn Wi-Fi off and send a message. If the app already knows it's offline, it says
  "Not connected. Reconnecting…" and keeps the text; if it hasn't noticed yet, the bubble shows a clock and, within
  about 10 s, "Not delivered". Turn Wi-Fi on and tap "!";
  scroll up in a long chat and watch older messages arrive without a jump; scroll up and get a message (the ↓ count).
- F-06: login screen and settings panel.
