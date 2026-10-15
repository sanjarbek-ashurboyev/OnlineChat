# 018 · The redesign stays in plain JavaScript, not React

- **Date:** 2026-10-15 · **Status:** Accepted (session 038, [frontend plan](../../frontend/plan.md))

## Problem
We are redesigning the frontend to look like Telegram and feel like an Apple app. Should we rewrite it in React
first, or keep the plain JavaScript in `assets/app.js`?

## Options considered
1. **Plain JS, split into ES modules** (`<script type="module">`, no build step). Motion from CSS, the View
   Transitions API and a small spring helper.
2. **React** (with Vite and Motion for React).
3. **Plain JS now, React later** if the app outgrows hand-written DOM updates.

## What we compared

| | Plain JS | React |
|---|---|---|
| Build setup | None: Django serves the files as they are | Node, `package.json`, a Vite build, `npm audit`, a build step in CI before the browser tests |
| The fixes in `app.js` | Stay where they are | Must be ported; each can come back (below) |
| Apple-style motion | CSS, View Transitions (Chrome 111+, Safari 18+, Firefox 144+), a spring helper; Motion's vanilla build has springs (about 18 KB) | Easier: Motion for React animates list reordering and exits with little code |
| Growing features | Harder: every update to the page is written by hand | Better: components and state scale well |
| Learning cost for the owner | Low | High: JSX, hooks, effects, npm, a bundler |

**How a React port could bring back bugs we already fixed:**
- Chat-switch race (P-21, `state.opened`): a `useEffect` that loads history without a cleanup step draws the old
  chat's messages into the new one.
- Logout drops old answers (H-04, `state.session`): a request finishing after logout updates the next user's screen.
- One shared refresh (T-07, decisions 014 and 016): React's development mode ("StrictMode") runs effects twice on
  purpose, so two refreshes race. Refresh tokens work once, so that is the race sessions 036 and 037 fixed.
- One socket per user (T-04, 5 sockets max): a socket opened in an effect is opened again on re-render.
- Read receipts for the open chat only (M-06): a handler keeps an old `activeId` (a "stale closure").

The browser tests would catch most of these, because they drive a real browser and don't care what built the page.
They don't cover everything: some fixes were checked by hand or by review.

## Chosen: 3 (plain JS now, React only if Phase 4 needs it)
The redesign is mostly CSS and small DOM changes. The risky part of the code (tokens, socket, catch-up) gains
nothing from React. The first task (F-01) splits `app.js` into ES modules, which keeps the logic apart from the
drawing code; that also makes a later move to React cheaper, because only the drawing part would change.

## Disadvantages and limits
- Every new UI state means writing the DOM update by hand; `renderChats()` rebuilds the whole list each time.
- Animating a list that reorders (FLIP) has to be written by us.
- No component library: buttons, menus and sheets are built from scratch.

## When another option is better
- **React (or a small alternative like Preact)** when Phase 4 arrives (groups, attachments, a media viewer) and
  hand-written DOM updates become the source of our bugs. Then port only the drawing layer: keep `api()`, the
  tokens, the socket and the catch-up as plain modules, and keep the browser tests' hooks so they prove the port.
