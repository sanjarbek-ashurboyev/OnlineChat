# 009 · Message history pages by cursor

- **Date:** 2026-10-11 · **Status:** Accepted (chosen by you in session 022, built in session 023)

## Problem
Codex audit M-11: history used offset pages (`?page=2` = "skip 50 from the newest"). Every new message shifted them,
so after 50 new messages "Load older" returned the page already on screen and made no progress.

## Options considered
1. **DRF `CursorPagination`** ordered by `-id`: built in; `next` is an opaque link anchored before the oldest message
   returned.
2. **Our own `?before=<id>`**, mirroring `?after=`: readable URLs, about 15 more lines of our own code and tests.

## Chosen: option 1
- No pagination code of our own; DRF's is widely used and tested.
- Same response shape as before (`next`, `previous`, `results`), so `app.js` changed only where it builds URLs.
- Ordering by `id` gives a total order (ids never tie), which also settles the "equal timestamps" part of audit risk
  R-05 for history.

## Disadvantages and limits
- **Opaque cursors:** you can't read or hand-write `?cursor=cD0xMjM0`. The client must follow `next`.
- **No "jump to page N".** Fine for a chat history.
- **Two paginators in one view:** history uses the cursor; `?after=` keeps numbered pages. The view picks one per
  request (`paginator` property).

## When another option is better
- **`?before=<id>`** if another client (a mobile app) needs to build history URLs itself, or wants to start from a
  known message (e.g. a search result) without a cursor.
