# 042 · F-04: the chat list (initials, new rows, rows that glide, a filter)

- **Date:** 2026-10-19 · **Phase:** Frontend redesign, Phase 1
- **Task:** F-04 in the [frontend plan](../../frontend/plan.md) · **Branch:** `f-04-chat-list`
- **Files:** `assets/js/avatar.js` (new), `assets/js/chats.js`, `assets/js/messages.js`, `assets/js/profile.js`,
  `assets/js/session.js`, `assets/app.css`, `templates/index.html`, `chats/test_browser.py`,
  `chats/test_browser_refresh.py`, docs
- **Objective:** a chat list that looks like Telegram's and moves like an Apple list: everyone has a face (their
  initials if no photo), and when a message arrives the chat slides to the top instead of the list blinking.

## What was done
1. **Tests first** (`chats/test_browser.py`, class `ChatRowTests`, 7 tests). On the F-03 code all 7 failed
   (2 failures, 5 errors):
   - someone without a photo gets their initials ("AV" for "Ali Valiyev") in the row and in the chat's header;
   - a new message for the bottom chat moves it to the top, and in the same frame it is still drawn where it was;
     then it slides into place and its `transform` is cleared;
   - a row that moves again half-way through a glide starts from where it is on screen (no jump);
   - with "reduce motion" the row is at the top at once;
   - typing filters the loaded chats by name ("ALI" → Alisher, Ali Valiyev); no match says so; a phone number says
     to press Search; Escape clears the filter;
   - the open chat's row has `aria-current="true"`, and only that one;
   - a focused row keeps focus when the list is redrawn (the poll) and when another row moves past it.
   On the old code the glide tests failed with `Cannot read properties of null`: the row they held had been thrown
   away, because every redraw rebuilt the whole list.
2. **`avatar.js`:** `initials(name)` (first letters of the first and last word; `Array.from` so an emoji counts as one
   letter) and `avatarSrc(user)`: the photo if there is one, else a small SVG with the initials on one of 7
   gradients, picked by `user.id % 7`. Used by the rows, the chat's header (`#peer-avatar`) and the ☰ menu.
3. **Rows kept between draws** (`renderChats` in `chats.js`): one row per chat id in a `Map`, filled in place. Only
   rows out of place are moved, and a focused row gets its focus back if it had to move.
4. **The glide (FLIP with a spring):** before a redraw, each row's place on screen is `offsetTop` plus its spring's
   value; after, the difference is the spring's start, and it springs to 0 (`response` 0.4, no bounce). The rising
   row gets `z-index: 1` so it passes over the rows making room.
5. **New rows:** 54px avatar; name and time on top; a two-line preview; the unread count right under the time; a
   hairline from the text to the edge (iOS style) instead of full-width borders; the online dot only when online
   (the header says it in words). With list and chat side by side, the open row is filled with the accent colour;
   on a phone it stays grey.
6. **Local filter:** the search field (now `type="search"`, placeholder "Search by name or phone") filters the
   loaded chats as you type; Search or Enter still looks up a phone number, as before. Filtering doesn't animate.
7. **Tests changed on purpose:** the placeholder "Find someone by phone…" became "Search by name or phone" in the two
   tests that use it (the field filters by name now, and a phone keyboard can't type names); the plan's hook list
   says so.
8. **Screenshots** (from a throwaway database, dropped afterwards) in `docs/frontend/screenshots/f-04/`: desktop with
   an open chat (light, dark), the filter (dark), the phone list (light, dark), and a row 60 ms into its glide.
9. **Results:** `make test` **177 run, OK (skipped=22)** (235 found). Real Postgres + Redis with
   `REQUIRE_BROWSER_TESTS=True`: **235 run, OK**, no `Too Many Requests` in the log. Ruff 0.16.10: all checks passed.
   ESLint (`no-undef`, `no-unused-vars`, run from outside the repo): no finding in the new code (its one finding,
   `atob` in `tokens.js`, was a global missing from the command's list).

**Not done:**
- **"You:" and ticks in the row.** The API's `last_message` is `{text, created_at}`: it doesn't say who sent it, so
  the list can't know it's yours. Needs `sender_id` and `id` in `last_message` (a small backend change; noted in the
  plan).
- The filter only sees loaded chats (the first page of 50 and any you showed with "Show more chats"). It matches
  names, not phone numbers: the list doesn't have them.
- New and removed rows appear and go at once; only rows that change place glide.
- Not tried on a real phone yet.

## Concepts

### FLIP
- **Simple definition:** First (where it is), Last (where the layout puts it), Invert (push it back with a
  `transform`), Play (animate the `transform` to zero).
- **Example:** Rustam's chat is fifth; his message arrives; the row is moved to the top in the page at once, but drawn
  where it was, then slides up while the four above slide down.
- Guide: [interface design](../concepts/interface-design.md#rows-that-glide-flip-with-a-spring-f-04).

### Keyed rendering
- **Simple definition:** keep one element per item (keyed by its id) and update it, instead of rebuilding the list.
- **Why here:** FLIP needs the same element before and after, and the keyboard's focus lives on an element: throw it
  away and focus is gone.

### `offsetTop` vs `getBoundingClientRect()`
- **Simple definition:** `offsetTop` is the element's place in the layout, ignoring transforms;
  `getBoundingClientRect()` is where it is drawn, transforms included.
- **Example:** a row 70 px down with `translateY(-30px)` has `offsetTop` 70 and is drawn at 40.

## Walkthrough

`assets/js/chats.js` (the heart of `renderChats`):
```js
const wasAt = new Map();
for (const [id, row] of rows) if (!row.li.hidden) wasAt.set(id, row.li.offsetTop + (row.glide?.value ?? 0));
...
let next = list.firstElementChild;
for (const chat of state.chats) {
  ...
  if (row.li === next) next = next.nextElementSibling;
  else list.insertBefore(row.li, next);
}
...
const offset = wasAt.get(id) - row.li.offsetTop;
if (animate && Math.abs(offset) >= 0.5) glide(row, offset);
```
- `wasAt` is measured *before* anything moves, including the part of an earlier glide still going.
- The loop walks the list once: a row already in its place is skipped, so only the chat that jumped to the top is
  moved, and nobody else loses focus.
- `glide` calls `spring.jump(offset)` (drawn where it was, in the same frame) and then `spring.to(0)`.

`assets/js/avatar.js`:
```js
const text = letters.replace(/[&<>"']/g, (c) => XML_ESCAPES[c]);
```
The name ends up inside SVG markup, so it is escaped first, just as messages use `textContent`, never `innerHTML`.

## Problems
- **Postgres and Redis containers were gone again**, and Docker Desktop wasn't running. `docker ps -a` showed no
  `onlinechat_db`/`onlinechat_redis`; the volumes `onlinechat_pgdata`/`onlinechat_redisdata` were there.
  `open -a Docker`, then `docker compose -p onlinechat up -d` from this worktree brought them back on the same volumes
  (`-p onlinechat` because the worktree's folder name would otherwise make a new, empty project). Root cause of the
  removal: **Hypothesis** (a `docker compose down` from another checkout, as in session 041); not checked.

## Decisions
- **Initials as an SVG in the `<img>`**, not a `<span>` with text: the rows, the header and the menu keep one kind of
  element and one line of code (`img.src = avatarSrc(user)`), and no test hook changes. The cost: the letters are part
  of a picture, which is fine because the name is written next to every avatar (`alt=""`).
- **Our spring for the glide**, not `el.animate()`: the spring already keeps position and speed, so interruption is
  free, and "reduce motion" is handled in one place (`motion.js`).
- **Filtering doesn't glide.** While typing, rows that jump around are noise; Apple's lists filter at once.
- **"You:" and ticks wait for the backend** rather than being guessed from live socket messages only: after a reload
  they would disappear, which is worse than not having them.

## What I should remember
- To animate a change of order: measure, change, invert, play (FLIP). Measure with `offsetTop` plus your own
  transform, not with the drawn position.
- Keep elements per id instead of rebuilding a list: animations need them, and so does focus.
- Moving a DOM node blurs it. Move only what's out of place, and give focus back.
- Anything you put inside markup (SVG included) must be escaped.

## Review questions
1. Why did the glide tests fail with `Cannot read properties of null` on the old code?
2. Why is "where the row is now" `offsetTop + glide.value`, and not `getBoundingClientRect().top`?
3. What makes a second glide start from where the row is, without a jump?
4. Why does the render loop move only rows that are out of place?
5. Why does the initials SVG escape the name?
6. Why aren't "You:" and the ticks in the row yet?

<details><summary>Answer key</summary>

1. The old `renderChats` emptied the list and built new rows each time. The test's row was removed from the page, so
   it had no parent (`row.parentNode` was `null`).
2. `offsetTop` is the layout place, which is what changes when the order changes. `getBoundingClientRect()` would also
   work for "before", but after the move we need the new layout place without our transform; using `offsetTop` for both,
   plus the spring's value we already know, keeps the two measurements consistent.
3. The spring's `value` is where the row is drawn; `wasAt` includes it, so the new offset is measured from the drawn
   place, and `jump(offset)` draws it exactly there before springing to 0.
4. Moving a node (even with `insertBefore`) takes focus off it. Moving only the chat that jumped keeps everyone
   else's focus, and the moved one gets it back.
5. A name like `<b>` or `A & B` would otherwise become SVG markup (broken picture, or worse). Escaping makes it text.
6. The API's `last_message` has only `text` and `created_at`. Without `sender_id` we can't tell our message from
   theirs after a reload.
</details>

## Next steps
- **You:** try the list on your phone: get a message from another account and watch the row slide up; type a name in
  the search field; turn on "Reduce motion".
- A small backend change: `sender_id` and `id` in `last_message`, then "You:" and ticks in the row.
- F-05: messages (wallpaper, tails, grouping, date dividers, SVG ticks, ↓ button, load on scroll, retry).
