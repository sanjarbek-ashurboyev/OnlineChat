# 038 · Frontend review and redesign plan

- **Date:** 2026-10-15 · **Phase:** Frontend redesign (Phase 1 planning)
- **Task:** review the frontend, plan a Telegram-like redesign with an Apple feel, choose plain JS or React
  · **Branch:** `f-00-frontend-plan`
- **Files:** `docs/frontend/plan.md`, `decisions/018-plain-js-not-react.md`, `concepts/frontend-architecture.md`, journal
- **Objective:** a reviewed starting point and an ordered list of small, testable frontend tasks.

## What was done
1. **Reviewed** `templates/index.html`, `assets/app.css` and `assets/app.js` on `main` `4ba822b`, against Telegram's
   layout and Apple's design principles. The table of gaps is in the [plan](../../frontend/plan.md#where-we-start-review-of-main-at-4ba822b).
2. **Listed what the browser tests depend on** (ids, classes, button names, and the globals `state`, `api`,
   `loadChats`, `start`, `pendingRevokes`, `revokeLogin` they call through `page.evaluate`). Any redesign must keep
   these or change the test in the same PR.
3. **Compared React with plain JS** and chose plain JS, split into ES modules ([decision 018](../decisions/018-plain-js-not-react.md)).
4. **Wrote the plan:** Phase 1 (F-01…F-06, look and feel), Phase 2 (frontend-only features), Phase 3 (features
   needing the backend), Phase 4 (big items, and the moment to reconsider React).

**Not done:**
- No code changed in this session; F-01 is the next branch.
- The bubble colour (green vs blue) is still open; it is needed before F-02.
- No screenshots of the current app were taken; F-02 starts with "before" screenshots to compare against.

## Concepts

### UI framework vs plain DOM
- **Simple definition:** plain JS changes the page element by element; a framework (React) lets you describe the
  page for the current data and makes the changes for you.
- **Why it mattered here:** our hard-won fixes live in plain JS. A rewrite would have to bring each one across.
- Guide: [frontend architecture](../concepts/frontend-architecture.md).

### Effects, StrictMode and stale closures
- **Effect:** React's place for side work (fetch, socket, timer), with a cleanup that runs before it runs again.
- **StrictMode:** in development React runs effects twice on purpose, to expose missing cleanups. With single-use
  refresh tokens (decision 016) that would create the exact two-refresh race we fixed.
- **Stale closure:** a function that keeps an old value (an old `activeId`) after the data changed.

### Interruptible motion (introduced; the guide comes with F-02)
- **Simple definition:** an animation you can grab or reverse at any moment, which starts from where the element is
  on screen *now*. Springs do this naturally; fixed-length CSS animations don't.

## Walkthrough
How a test reaches into the app today (`chats/test_browser.py`):
```python
page.evaluate("state.access = 'expired'; api('/auth/profile/').then((p) => p.id, (e) => e.status)")
```
This works because `app.js` is a classic script: its top-level `const state` and `function api` are visible to any
other script on the page. Inside an ES module they are private to the module, so F-01 has to hand these names to
the page on purpose, or the tests lose them.

## Problems
None in this session.

## Decisions
- [018](../decisions/018-plain-js-not-react.md): plain JS now; React only if Phase 4 needs it, and then only for
  the drawing layer.

## What I should remember
- A rewrite only removes bugs if the new code carries every fix across; tests that drive a real browser are what
  prove it.
- The tests depend on ids, classes, names and a few globals: that list is the contract of the redesign.
- Motion should start from the current on-screen value, so it can always be interrupted.

## Review questions
1. Name two bugs we already fixed that a React port could bring back, and say how.
2. Why would the browser tests still be useful if we moved to React?
3. Why does turning `app.js` into an ES module break `page.evaluate('state.refresh')`?
4. Why does F-01 (the module split) come before any visual change?
5. What makes an animation "interruptible"?

<details><summary>Answer key</summary>

1. The chat-switch race: an effect without a cleanup draws chat A's late history into chat B. The double refresh:
   StrictMode runs effects twice, so two refreshes spend the same single-use token. (Also: a second socket opened
   on re-render; a stale `activeId` sending read receipts for the wrong chat.)
2. They drive a real Chromium and look at the page through ids, classes and names. They don't care whether plain JS
   or React built it.
3. A module's top-level names are private to the module. A classic script's top-level names are shared with every
   script on the page, which is what `page.evaluate` relies on.
4. It changes no behaviour, so the unchanged tests prove it, and it separates logic from drawing code before the
   redesign starts changing the drawing code.
5. It can be stopped or reversed at any moment without waiting, and the new motion starts from where the element is
   on screen now (and with its current speed), so nothing jumps.
</details>

## Next steps
- F-01: split `app.js` into ES modules with no behaviour change.
- Choose the bubble colour before F-02.
