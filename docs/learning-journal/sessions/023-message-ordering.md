# 023 · Codex audit: message ordering, gaps and paging

- **Date:** 2026-10-11 · **Phase:** Stage 0
- **Task:** findings M-03, M-09, M-10 and M-11 from [Codex's second audit](../../scaling/05-codex-audit-2026-10-11.md)
  (PR B of the "message consistency" group) · **Branch:** `fix-message-ordering`, stacked on `fix-message-receipts`
  (PR #32), so merge #32 first
- **Files:** `chats/views.py`, `assets/app.js`, `chats/tests.py`, `chats/test_browser.py`, docs
- **Objective:** messages always show in order; a message missed in the middle is fetched; "load older" and
  "show more chats" never repeat or skip a page.

## Before we started
- Stacked on PR #32, because both change the same parts of `app.js` and the same docs.
- Your choice from session 022: DRF `CursorPagination` for history ([decision 009](../decisions/009-cursor-pagination-for-history.md)).

## What we accomplished
1. **Tests first.** On the old code, 5 new tests failed, each reproducing the audit's numbers:
   - M-11 (REST): after 50 new messages, the second page returned `old 59 … old 10` (the page already shown)
     instead of `old 9 … old 0`;
   - M-09 (browser): a live message that beat the history was drawn first: `['newest', 'older 1', 'older 2']`;
   - M-03 (browser): with a hole in the middle, the reconnect fetched only after the newest message: 2 rows, not 3;
   - M-10 (browser): one failed "Load older" skipped a page: 70 rows instead of 100;
   - M-10 (browser): two clicks on "Show more chats" made 2 requests for page 2.
2. **M-11:** `HistoryPagination(CursorPagination)` with `ordering = '-id'`. The view's `paginator` property picks it for
   history and keeps numbered pages for `?after=`. History is ordered by `id`, not `created_at`.
3. **M-09:** `appendMessage()` inserts each row in id order, searching from the bottom. History, live messages and
   catch-up can arrive in any order.
4. **M-03:** `state.syncedUpTo` = the newest id we know we hold *everything* up to. The first history page sets it;
   catch-up fetches `?after=syncedUpTo` and moves it; live messages don't move it. The socket now catches up on
   **every** connect (not only reconnects) and reloads the chat list each time.
5. **M-10:** "Load older" and "Show more chats" allow one request at a time (flag + disabled button) and move their
   pointer only when the page arrives; a failure leaves it, so the next click retries the same page. `logout()` resets
   the flags, because a dropped answer never reaches its `finally`.
6. **Results:** browser suite **23 OK**. `make test` → **122 run, OK (11 skipped)**. Real Postgres + Redis → **145 tests,
   OK**, twice in a row. `ruff check .` clean. OpenAPI `--validate`: 0 errors, the same 13 warnings as before (M-20).

**Not done:**
- **Late commits** (audit risk R-05): if message 5 commits after 6, a catch-up between them moves `syncedUpTo` past 5.
  Not reproduced; needs a real concurrency test.
- The chat list still uses offset pages (see the [pagination guide](../concepts/pagination.md), section 5).
- One extra chat-list request on each page load (the first socket connect now reloads it).

## Concepts I learned
- [Pagination: offsets vs cursors](../concepts/pagination.md) (new guide).

### A sync boundary
- **Simple definition:** the point up to which you *know* you have everything, as opposed to the newest thing you've
  *seen*. Live events can skip; only fetches move the boundary.
- **Everyday example:** reading a numbered newspaper series. Having issue 12 doesn't mean you have 11. Your boundary is
  the last issue before your first gap.

### Insert in order instead of append
- When several sources deliver items (history, live, catch-up), don't trust arrival order: give every row a sort key
  (`data-id`) and insert in place.

## Important code walkthrough

### `chats/views.py`
```python
class HistoryPagination(CursorPagination):
    ordering = '-id'

@property
def paginator(self):
    if not hasattr(self, '_paginator'):
        catching_up = 'after' in self.request.query_params
        self._paginator = PageNumberPagination() if catching_up else HistoryPagination()
    return self._paginator
```
- DRF's `GenericAPIView.paginator` builds `pagination_class()` once per request; overriding the property lets one view
  use either.

### `assets/app.js`: rows in id order
```js
let above = rows.lastElementChild;
while (above && Number(above.dataset.id) > msg.id) above = above.previousElementSibling;
if (above) above.after(row);
else rows.prepend(row);
```
- Usually the new row belongs at the bottom, so the loop stops at once. An older page walks further, which is fine for
  hundreds of rows.

### `assets/app.js`: catch-up from the boundary
```js
const data = await api(`/chats/${chatId}/messages/?after=${state.syncedUpTo}`);
...
state.syncedUpTo = Math.max(state.syncedUpTo, ...data.results.map((m) => m.id));
```
- Messages already on screen come back too (they're after the boundary) and are skipped by `seenIds`. Fetching a
  little extra is the price of never missing one.

## Problems we encountered
- [P-31 · Messages out of order, holes never filled, pages repeated or skipped](../problems-and-solutions.md#p-31--messages-out-of-order-holes-never-filled-pages-repeated-or-skipped)
- **A regex in a test was escaped twice.** Writing a test through a Python script that itself wrote Python turned
  `\?` into `\\?`, so the route never matched and an old test errored with `IndexError`. Fixed and checked with
  `grep re.compile`.

## Engineering decisions and trade-offs
- [Decision 009](../decisions/009-cursor-pagination-for-history.md): cursor pagination for history.
- **Reload the chat list on every connect** (one extra request at page load) rather than only after reconnects, so a
  message that arrives between the first list load and the socket being ready isn't missed.
- **Sort in the DOM** rather than keeping a sorted array and re-rendering: smaller change, and rows that are already
  drawn don't flicker.

## What I should remember
- Offsets move when the list grows; anchor pages to an item.
- "Newest seen" isn't "everything up to". Keep a boundary that only fetches move.
- Don't trust arrival order; insert by a sort key.
- Move a page pointer only after the page arrives, and allow one request at a time.

## Review questions
1. Why did "Load older" stop making progress after many new messages?
2. What does the cursor in `next` encode, and why can't new messages shift it?
3. The page has messages 1 and 3; 2 was lost live. Old code vs new code: what does a reconnect fetch?
4. Why don't live messages move `syncedUpTo`?
5. Two quick clicks on "Show more chats": what happened before, and what stops it now?
6. Why does `logout()` reset `loadingOlder`, when the click handler's `finally` already does?

<details><summary>Answer key</summary>

1. Page 2 meant "skip the 50 newest". 50 new messages made the old page 1 the new "skip 50" result, so page 2
   returned what was already shown.
2. "Before id N", where N is the oldest id returned. New messages get larger ids, so the set of messages before N
   doesn't change.
3. Old: `?after=3` (the newest seen), so 2 is never fetched. New: `?after=1` (the boundary from the history load), so 2
   and 3 come back; 3 is skipped as already seen, 2 is inserted between.
4. A live message proves only that it arrived, not that nothing before it was lost. Only a fetch (which returns
   everything after its boundary) proves completeness.
5. Both clicks fetched page 2 and both added 1 to the page counter, so the next click asked for page 4 and page 3 was
   never shown. Now a flag (and the disabled button) refuses the second click while the first is in flight.
6. If logout happens during the request, `api()` returns a promise that never settles, so the `finally` never runs.
   Without the reset, the flag would stay `true` and block the next account's button.
</details>

## Next steps
- Merge PR #32, then this PR.
- Remaining audit items: privacy and uploads (M-14, M-15, M-16), contracts and test infrastructure (M-20, M-22), and
  the deployment/measurement risks R-01…R-07.
