# 004 · Test the frontend with Playwright, in a real browser

- **Date:** 2026-10-11 · **Status:** Accepted

## Problem
`assets/app.js` had no tests. A review (Codex) found four bugs there: a slow answer for one chat landing in another,
"load older" in reverse order, chats after the first 50 unreachable, and a rejected message losing its text.
Fixing them without tests means nothing stops them from coming back.

## Options considered
1. **Playwright end-to-end tests**, run by Django's test runner against a live server (`ChannelsLiveServerTestCase`).
2. A manual check in the browser for each fix, like T-09.
3. Node's built-in test runner on small functions pulled out of `app.js`.

## Chosen: option 1
- It tests the real `app.js` against the real server and WebSocket, the way users meet it.
- Playwright can hold a request and release it later (`page.route`), so timing bugs like the chat switch can be
  reproduced every time, not by luck.
- It runs in the existing runner and CI job, so there's no new tool to learn besides Playwright itself.

## Disadvantages and limits
- **New dependency** (`playwright`, plus `greenlet` and `pyee`) in `requirements.txt`, which production installs too.
  It's ~40 MB but never imported by the app. A separate `requirements-dev.in` would fix that; not worth a second
  file for one package yet.
- **Slower:** the 6 tests take about 30 s locally, and CI downloads Chromium (~1 min).
- **Only with Postgres and Redis:** Daphne runs in another process, which can't see SQLite in memory or the
  test's mocks. `make test` skips them; run them with Docker up.

## When another option is better
- Node unit tests, once `app.js` is split into modules with pure functions worth testing alone.
- A manual check, for a one-off visual change that a test can't judge (layout, colours).
