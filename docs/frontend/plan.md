# Frontend redesign plan: Telegram's layout, Apple's feel

*Written: 2026-10-15 (session 038). Decision on the technology: [018](../learning-journal/decisions/018-plain-js-not-react.md).*

The goal: make OnlineChat look and feel like a modern messenger. **Layout and features come from Telegram**
(its iOS/macOS app, which already follows Apple's guidelines). **The feel comes from Apple's design principles:**
instant response, motion you can interrupt, springs, translucent materials, careful type.

We copy ideas, not assets: our own icons, our own wallpaper pattern, our own logo.

## Where we start (review of `main` at `4ba822b`)

The frontend is three files: `templates/index.html` (126 lines), `assets/app.css` (355) and `assets/app.js` (934).

**Keep:** the logic. Every race and session bug from the Codex audits is fixed in `app.js` and guarded by the
browser tests (`chats/test_browser.py`, `chats/test_browser_refresh.py`). Messages are drawn with `textContent`,
never `innerHTML`. Dark mode follows the system. Phones get a list/chat view switch.

**Change:**

| Area | Now | Target |
|---|---|---|
| Icons | Emoji (`⚙ ⏻ 🔍 ←`), a text "Send" button | One SVG icon set, round icon buttons with `aria-label` |
| Sidebar top | Own avatar + ⚙ + ⏻ | ☰ opens a drawer (profile, settings, log out); rounded search bar |
| Chat rows | 40px avatars, borders, badge inside the preview | 54px avatars, no borders, badge right under the time, "You:" prefix, ticks, accent-coloured selected row |
| Avatars | Grey silhouette | Coloured circle with initials |
| Message area | Plain background, identical bubbles | Our own wallpaper, bubbles with tails, grouped runs from one sender |
| Dates | None | "Today" / "14 October" dividers |
| Time and ticks | A line under the text, `✓` characters | Inline at the bottom right, SVG ticks |
| History | "Load older messages" button | Loads on scroll up; a ↓ button with the new-message count |
| Connection | 8px coloured dot | Header text: "Connecting…", "Waiting for network…" |
| Composer | Boxed textarea + "Send" | Rounded field; send icon appears when there is text |
| Send failure | Error line under the composer | Red "!" on the bubble, tap to retry |
| Profile | Dialog with a raw file input | Settings panel in the sidebar, tap the avatar to change it |
| Login | Generic card with tabs | Logo, large title, one centred form |

## Design rules (from Apple's design talks)

- **Response:** feedback on pointer-down (a slight scale-down), never only on release. `touch-action: manipulation`
  removes the tap delay on phones.
- **Interruptible motion:** no input is blocked during a transition. Every animation starts from where the element is
  *on screen now*, so tapping "back" mid-slide reverses it smoothly.
- **Springs:** critically damped (no bounce) by default; a little bounce only after a flick.
- **Same path in and out:** a chat slides in from the right and leaves to the right. Menus grow out of what you tapped.
- **Gestures:** swipe from the left edge to go back follows the finger 1:1; the release speed and direction decide
  whether it commits. Later: swipe a message left to reply.
- **Materials:** the chat header and composer are frosted (`backdrop-filter`) with messages scrolling under them;
  a soft fade where content meets them instead of 1px borders.
- **Type:** the system font; tighter tracking on titles; sizes in `rem` so the user's text size setting works.
- **Accessibility:** `prefers-reduced-motion` turns slides into short cross-fades; `prefers-reduced-transparency` and
  `prefers-contrast: more` get solid surfaces. Status is never shown by colour alone.

## Rules for every PR

1. **The browser tests are the safety net.** They find elements by these hooks; keep them, or change the test in the
   same PR and say why:
   - ids: `#auth`, `#auth-form` (inputs `phone_number`, `password`), `#auth-submit`, `#auth-error`, `#app`,
     `#chat-list li`, `#logout`, `#peer-name`, `#peer-status`, `#peer-avatar`, `#conn-state.is-open`,
     `#message-rows .row` (`.row.out`, `.bubble`, `.meta`), `#composer-input`, `#send-error`
   - classes: `.chat-name`, `.badge`; `.row.out .meta` ends with `✓✓` when read
   - accessible names: "Show more chats", "Load older messages", the chat row's name; placeholder
     "Find someone by phone…"
   - globals the tests call through `page.evaluate`: `state`, `api`, `loadChats`, `start`, `pendingRevokes`,
     `revokeLogin`
2. **Checked:** `make test`, the browser tests on real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True`, Ruff, and
   screenshots in light, dark and phone width.
3. **One branch per task** from a fresh `main`, named `f-NN-short-name`, with a journal session.

## Phase 1: look and feel (frontend only)

| Task | What | Done when |
|---|---|---|
| **F-01** | Split `app.js` into ES modules, no behaviour change | All browser tests pass unchanged |
| **F-02** | Design system: colour roles (light/dark), type scale, SVG icons, materials, a spring helper, press feedback, reduced motion/transparency/contrast | A token sheet in CSS; icons have `aria-label` |
| **F-03** | Layout and navigation: frosted header and composer, push/back transitions on phones with the edge swipe, ☰ drawer | **You try it on your phone** before F-04 |
| **F-04** | Chat list: initials avatars, new rows, rows glide when a chat moves to the top, local filter | |
| **F-05** | Messages: wallpaper, tails, grouping, date dividers, SVG ticks, ↓ button, load on scroll, "Not delivered" + retry | |
| **F-06** | Login screen and the settings panel | |

## Phase 2: features with no backend change

Drafts per chat · unread count in the tab title · desktop notifications · light/dark switch · clickable links
(built as DOM elements, never `innerHTML`) · "Copy text" on a message · "last seen 5 minutes ago".

## Phase 3: features that need the backend

Each is a task with tests written first: typing indicator (a socket action with no database write, rate-limited
like T-04) · reply (later with swipe-to-reply) · edit · delete for me / for everyone · search in messages ·
pin, mute and archive.

## Phase 4: big items, each with its own decision

Photos, files and voice messages · reactions · group chats (they change `Chat(user1, user2)` and the scaling plan).
Reconsider React here ([decision 018](../learning-journal/decisions/018-plain-js-not-react.md#when-another-option-is-better)).

## Open choices

- **Bubble colours:** Telegram's light green on a patterned wallpaper (proposed) or iMessage blue on plain. Needed
  before F-02 sets the colour roles.
- **Order with the scaling plan:** the redesign starts now (2026-10-15); the remaining Stage 0 tasks wait or alternate.
