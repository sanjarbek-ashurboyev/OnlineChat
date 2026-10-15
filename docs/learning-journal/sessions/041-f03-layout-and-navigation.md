# 041 · F-03: layout and navigation (glass, ☰ menu, swipe back)

- **Date:** 2026-10-15 · **Phase:** Frontend redesign, Phase 1
- **Task:** F-03 in the [frontend plan](../../frontend/plan.md) · **Branch:** `f-03-layout-navigation`
- **Files:** `assets/js/motion.js` (new), `assets/js/nav.js` (new), `assets/js/messages.js`, `assets/js/session.js`,
  `assets/js/socket.js`, `assets/app.css`, `templates/index.html`, `chats/test_browser.py`, `GOTCHA.md`, docs
- **Objective:** the app's first change you *feel*: glass over the messages, a ☰ menu, the connection in words, and
  on a phone a chat that slides in and is swiped away, all interruptible.

## What was done
1. **Tests first** (`chats/test_browser.py`, class `LayoutTests`, 5 tests). On the F-02 code all 5 failed:
   - the connection in words: "Chats" when connected; "Waiting for network…" in the list title and the chat's status
     line when offline; reconnected and "Chats" again once back online;
   - the ☰ menu opens, shows your name, closes with Escape, and focus returns to ☰;
   - on a phone (390×844, touch): opening a chat makes the list `inert`; Back makes the chat `inert` and clears
     `state.activeId`;
   - a fast swipe right (real touch input through Chromium's DevTools protocol) goes back;
   - a short slow drag (60 px over 400 ms) springs back to the chat.
2. **`motion.js`:** `createSpring` (Apple's response and damping ratio; moves on from the current value and speed),
   `project` (where a flick would land), `rubberband`, and `trackHorizontalDrag` (10 px before deciding, 1:1 tracking,
   speed over the last 100 ms). With "reduce motion" on, a spring arrives at once.
3. **`nav.js`:** `setView('list' | 'chat')` slides the chat over the list on a phone (`--pane-x`, the list drifts 30%
   left and dims), keeps the off-screen panel `inert`, and handles swipe-back. The ☰ menu is a `<dialog>` (focus, Escape
   and the modal behaviour come free) with our own scrim and panel, opened and closed by a spring, and dragged closed
   with the same gesture code.
4. **Moved into the menu:** your avatar, name and phone, Profile, Log out. The list's header is now ☰ and a title.
5. **Connection in words** (`socket.js`): the list title is "Chats", "Connecting…" or "Waiting for network…"; in an
   open chat the status line shows the same instead of "online/last seen". The coloured dot is gone. Coming back online
   reconnects at once instead of waiting out the backoff.
6. **Glass:** the chat header and composer stick to the edges of the one scrolling area (`position: sticky`), with a
   translucent background and `backdrop-filter`; few messages sit at the bottom by the composer. Solid with
   `prefers-reduced-transparency`.
7. **Tests changed on purpose:** `#logout` is inside the closed menu now, so the 10 clicks on it became
   `self.log_out(page)` (☰, then Log out). `open_app()` takes browser-context options (a phone's viewport and touch).
8. **One bug on the way** (P-47): the swipe test still failed, because `touch-action` was on `.pane`, not on the
   scrolling `.messages`. Fixed; the test then passed.
9. **Screenshots** (from the throwaway database): desktop light/dark, phone chat light/dark, the menu on desktop and
   phone, and the glass with messages scrolled under it, in `docs/frontend/screenshots/f-03/`.
10. **Results:** `make test` **177 run, OK (skipped=21)**; Ruff 0.16.10 clean; ESLint (`no-undef`,
    `no-unused-vars`, outside the repo) clean. Real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True`: first full run
    **228 run, 2 errors** (log not kept; see Problems), second **228 OK**, third after a one-minute pause **228 OK**
    with no `Too Many Requests` in the log.

**Not done:**
- **You haven't tried it on a phone yet:** the plan's gate before F-04. Real fingers find what scripts don't.
- On iPhone Safari a swipe from the very left edge is the browser's own "back" and leaves the page; our swipe works
  from anywhere else on the chat. Installed as a home-screen app it doesn't happen.
- Dragging the menu closed has no test (the menu's Escape and the phone's swipe do).
- The profile dialog is unchanged (F-06).

## Concepts

### Springs
- **Simple definition:** a value pulled toward a target with a speed of its own; it can be sent elsewhere at any
  moment and bends instead of jumping.
- **Example:** tap a chat, then Back while it's still sliding in: it turns around where it is.
- Guide: [interface design](../concepts/interface-design.md#springs-motion-you-can-interrupt-f-03).

### Gestures: follow, then decide by projection
- **Simple definition:** track the finger exactly; on release, compute where the flick would land and decide from
  that, then let the spring continue at the finger's speed.

### `inert`
- **Simple definition:** an attribute that makes a part of the page unclickable, unfocusable and invisible to screen
  readers, while still drawn. Used for the panel that is off screen.

### `touch-action`
- **Simple definition:** CSS telling the browser which finger gestures it may handle itself (scroll, zoom). What it
  doesn't take, the page gets as pointer events. It counts on the scrolling element the touch starts in (P-47).

## Walkthrough

`assets/js/nav.js` (swipe back):
```js
trackHorizontalDrag(pane, {
  canStart: (e, dx) => narrow.matches && app.dataset.view === 'chat' && dx > 0,
  onStart: () => { paneGrabbedAt = paneSpring.value; },
  onMove: (dx) => {
    const x = paneGrabbedAt + dx;
    paneSpring.jump(x < 0 ? rubberband(x, pane.offsetWidth) : x);
  },
  onEnd: (velocity) => {
    if (paneSpring.value + project(velocity) > pane.offsetWidth / 2) leaveChat({ velocity });
    else paneSpring.to(0, { velocity });
  },
});
```
- `jump` while the finger holds it (no animation); `to` with the finger's `velocity` once it lets go.
- `project(velocity)`: a 1,000 px/s flick adds about 500 px, so a quick flick from near the left counts as a full swipe.
- `leaveChat` is the same function the Back button calls: one way to leave a chat, whatever the input.

`assets/js/motion.js` (one spring step):
```js
velocity += (-stiffness * (value - target) - damping * velocity) * (dt / steps);
value += velocity * (dt / steps);
```
A new `target` changes only the pull; `value` and `velocity` carry on, which is why it never jumps.

`assets/js/socket.js`:
```js
const words = open ? 'Chats' : navigator.onLine ? 'Connecting…' : 'Waiting for network…';
```

## Problems
- **P-47:** `touch-action` on the wrong element; the browser kept the sideways drag. Root cause **Confirmed** (the
  test fails without the one-line fix and passes with it).
- **Postgres and Redis were gone mid-session:** `docker ps -a` no longer listed `onlinechat_db`/`onlinechat_redis`
  (removed by a `docker compose down` from the main checkout, not from this branch). The volumes were intact;
  `docker compose up -d` from the main checkout brought them back with the same data.
- **Intermittent test failures from throttling:** running the browser tests three times within ~70 s gave one
  failure (`test_a_late_401…`: the socket never opened after logging in), and the log shows
  `Too Many Requests: /api/v1/auth/login/`. That is the known trap in `GOTCHA.md` (shared Redis throttle counters).
  Root cause **Confirmed** for that run. The first full run's 2 errors (`test_the_socket_connects_even_if_the_chat_list_fails_to_load`,
  `test_a_slow_answer_for_the_previous_chat_is_ignored`) came after several runs in a few minutes too, and both pass
  alone; their log wasn't kept, so for those the same cause is a **Hypothesis**.

## Decisions
- **The menu is a native `<dialog>`** opened with `showModal()`: focus moves in, Escape works, the page behind can't
  be clicked, and closing returns focus to ☰. We draw our own scrim inside it, because the scrim's opacity follows the
  drawer through a CSS variable, and in older browsers `::backdrop` can't read the dialog's variables.
- **Sticky header and composer inside the scrolling area,** instead of fixed bars with measured padding: no
  JavaScript, and the glass works because the messages really pass under them.
- **Swipe back from anywhere on the chat**, not only from the edge: the edge belongs to Safari's own back gesture.
- **Damping 1 everywhere** (no bounce): an overshooting drawer or chat would open a gap at the screen's edge.

## What I should remember
- Interruptible motion = start from the current value and speed. Springs do that; CSS transitions don't.
- Decide a gesture by where the flick would land, then hand its speed to the animation.
- `touch-action` belongs on the scroller the finger is in.
- Running the browser tests twice within a minute can fail on throttles; wait a minute, read the log for 429s.

## Review questions
1. Why does the Back button feel different from before if you tap it while a chat is still sliding in?
2. What does `project(velocity)` add, and why decide with it instead of the release position?
3. Why does the outgoing panel get `inert` only after it has left?
4. Why did the swipe test fail with `touch-action` on `.pane`?
5. Why is the ☰ menu a `<dialog>`, and why doesn't it use `::backdrop` for the dark layer?
6. What would you check first if a browser test fails right after another test run?

<details><summary>Answer key</summary>

1. The spring keeps the chat's current position and speed and just changes the target, so the chat turns around where
   it is. A fixed animation would jump or have to finish first.
2. The distance a flick would carry on (like a scroll slowing down). A short, fast flick then counts like a long swipe,
   which is what the user meant; the release position alone would ignore the speed.
3. So a finger can still catch it on the way out; once it has left, nothing off screen can be focused or read aloud.
4. The browser looks at `touch-action` from the touched element up to the nearest scrolling element (`.messages`).
   `.pane` is above that, so it was ignored, and `.messages` allowed every gesture: the browser kept the drag.
5. `showModal()` gives focus handling, Escape, a blocked background and focus return for free. The dark layer's
   opacity follows the drawer through a CSS variable, and in older browsers `::backdrop` can't read the dialog's
   variables; an element inside the dialog always can.
6. Whether it was throttled: look for `Too Many Requests` in the log, wait a minute, and run it again alone.
</details>

## Next steps
- **You:** try it on your phone (same Wi-Fi: `http://<this Mac's IP>:<port>/`): open and swipe away chats, open the ☰
  menu and drag it closed, turn "Reduce motion" on and off.
- F-04: chat list (initials avatars, new rows, rows that glide to the top, local filter).
