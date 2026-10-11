# Pagination: offsets vs cursors

*First used in [session 023](../sessions/023-message-ordering.md) (Codex audit M-11).*

## 1. Simple definition

**Pagination** splits a long list into pages. There are two common ways to say which page you want:
- **Offset:** "skip 50, give me the next 50" (`?page=2`). The page is a *position* in the list.
- **Cursor:** "give me the 50 just before *this* item" (`?cursor=…`). The page is anchored to an *item*.

## 2. Why it exists

Nobody loads 10,000 messages at once: it's slow for the server, the network and the browser. Pages load what the
screen needs, then more on demand ("Load older messages").

## 3. How it works, step by step

**Offset** (`LIMIT 50 OFFSET 50`): the database sorts, skips 50 rows, returns 50. If 50 new messages arrive between
two requests, everything moves down 50 places, and "skip 50" now lands on the page you already have.

**Cursor** (DRF's `CursorPagination`, `ordering = '-id'`): the first page returns the 50 newest, plus a `next` link
whose cursor encodes "before id N", N being the oldest id returned. The next request is
`WHERE id < N ORDER BY id DESC LIMIT 50`. New messages have larger ids, so they can't change what is "before N".

## 4. Small example

Messages 1–110 exist; the screen shows 61–110 (newest 50). Then 50 new messages (111–160) arrive.

| Next request | Returns | Correct? |
|---|---|---|
| `?page=2` (offset 50) | 61–110 again | No: a repeat, and 11–60 are never shown |
| `?cursor=<before 61>` | 11–60 | Yes |

## 5. In our project

- **Message history** (`chats/views.py`, `HistoryPagination`): cursor, newest first, by `id`. `app.js` keeps the `next`
  link's query string in `state.olderQuery` and only moves it when a page arrives.
- **Catch-up** (`?after=<id>`): already anchored to an id, oldest first. It keeps numbered pages because the client
  only checks whether there is a `next` (more than a page missed → reload the chat).
- **Chat list** (`/chats/`): still offset pages. Its order changes as chats get new messages, so a cursor on a moving
  sort key doesn't fit; the 45 s poll and duplicate filtering cover it.

## 6. Alternatives

- **Our own `?before=<id>`:** the same idea as the cursor, with readable URLs. More code of our own to test.
- **Keyset on two columns** (`created_at, id`): needed when the sort key can tie. Ids never tie, so one column is enough.
- **Infinite offset with de-duplication on the client:** hides repeats but never shows the skipped messages.

## 7. Common mistakes

- **Offset pages over a list that grows at the top.** Pages repeat or skip.
- **Sorting by a value that can tie** (`created_at`) without a tie-breaker: rows with equal values can swap between
  pages, or be missed. We sort by `id`.
- **Moving the page pointer before the page arrives.** A failed request then skips a page (Codex audit M-10). Move it
  on success.
- **Allowing two "load more" requests at once.** Both fetch the same page. Guard with an in-flight flag and disable the
  button.

## 8. When to use it

Cursors for feeds and chat histories (new items keep arriving, users scroll back). Offsets for small, stable lists
where "jump to page 7" matters, such as an admin table.
