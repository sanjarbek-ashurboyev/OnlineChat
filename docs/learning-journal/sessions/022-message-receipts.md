# 022 · Codex audit: delivery failures and read receipts

- **Date:** 2026-10-11 · **Phase:** Stage 0
- **Task:** findings M-04, M-06, M-07 and M-08 from [Codex's second audit](../../scaling/05-codex-audit-2026-10-11.md)
  (PR A of the "message consistency" group) · **Branch:** `fix-message-receipts`
- **Files:** `chats/consumers.py`, `chats/views.py`, `chats/serializers.py`, `assets/app.js`, `chats/tests.py`,
  `chats/test_consumers.py`, `chats/test_browser.py`, docs
- **Objective:** a saved message is never reported as failed; a read covers only what was on screen, reaches the
  sender over either door, and is repaired if its notification was lost.

## Before we started
- PR #31 merged (`8fb189b`). Branched `fix-message-receipts` from the updated `main`.
- **Your choices:** DRF CursorPagination for history (next PR), a read-up-to boundary for receipts
  ([decision 008](../decisions/008-read-up-to-boundary.md)), and two PRs: this one (M-04, M-06–M-08), then ordering
  and paging (M-03, M-09–M-11).

## What we accomplished
1. **Tests first.** On the old code:
   - 7 REST tests in `chats/tests.py` errored or failed: no `peer_read_up_to`; no `broadcast_read`; a failed
     broadcast raised `ConnectionError` instead of answering 201.
   - 5 socket tests in `chats/test_consumers.py` failed: the read event had no `up_to`; a read marked 2 messages
     instead of 1; no error for a missing `up_to`; no event after a REST read; and a failed `group_send` crashed the
     consumer.
   - 3 browser tests failed: the read frame had no `up_to`; one receipt ticked `[2, 2]` instead of `[2, 1]`; a lost
     receipt stayed `✓` after the poll.
2. **M-06/M-07:** `chats/consumers.py` now has `mark_read(chat, reader, up_to)` and `broadcast_read(...)`, used by
   both the socket's `read` action and `POST /chats/<id>/read/`. `up_to` is required: a whole number ≥ 0 (not a
   boolean). The event is `{type: 'read', chat_id, by, up_to, count}`.
3. **M-08:** the chat list has `peer_read_up_to`: the newest of my messages the other person has read
   (`Max('messages__id', filter=…)`). `loadChats()` applies it to the open chat, so the 45 s poll and every reconnect
   repair missed ticks.
4. **M-04:** if broadcasting fails after a save, REST still answers 201 and logs it; the socket logs it and sends the
   echo straight to the sender's own socket, so the browser knows it was saved.
5. **Frontend:** `sendRead()` sends `up_to = max(seenIds)` (skips an empty chat); `showReadUpTo(id)` ticks only rows with
   `data-id <= id`.
6. **Results:** browser suite **19 OK**. `make test` → **121 run, OK (10 skipped)**. Real Postgres + Redis → **140 tests,
   OK**. `ruff check .` clean; `makemigrations --check` → no changes.

**Not done:**
- **M-03** (a message missing in the middle is never fetched) is the next PR. Until then, `up_to` can cover a gap.
- Other clients of the read endpoint would now need `up_to`; ours is the only one.
- The chat list's extra `Max` aggregate isn't measured (audit risk R-04).

## Concepts I learned

### A boundary instead of a list
- **Simple definition:** "everything up to id N" summarises a contiguous run in one number.
- **Everyday example:** a bookmark. You don't list every page you've read, you say "up to page 120".
- **Here:** `up_to` in reads, and `peer_read_up_to` in the chat list.

### Save first, then notify, and never confuse the two
- The database write is the fact; the notification is a hint. If the hint fails, the fact still holds: report success
  for the save and log the hint's failure.

### One function, two doors
- REST and the socket now call the same `mark_read()` and send the same event. A future rule (e.g. "can't read in a
  blocked chat") is added once (the P-20 lesson again).

## Important code walkthrough

### `chats/consumers.py`
```python
def mark_read(chat, reader, up_to):
    return (
        chat.messages
        .filter(is_read=False, id__lte=up_to)
        .exclude(sender=reader)
        .update(is_read=True, read_at=timezone.now())
    )
```
- `id__lte=up_to` is the whole M-06 fix on the server: later messages keep `is_read=False`.
- `.update()` returns how many rows changed, which becomes `count` in the event.

```python
try:
    for user_id in (chat.user1_id, chat.user2_id):
        await self.channel_layer.group_send(group_for_user(user_id), event)
except Exception:
    logger.exception('inbox: broadcast failed for message %s', message.pk)
    await self.chat_message(event)
```
- `self.chat_message(event)` is the same handler a group event would call, so the sender's page gets a normal echo.

### `chats/views.py`: the chat list
```python
peer_read_up_to=Max('messages__id', filter=Q(messages__sender=me, messages__is_read=True)),
```
- The highest id among *my* messages that are read. `None` when nothing of mine has been read.

### `assets/app.js`
```js
function sendRead(chatId) {
  if (chatId !== state.activeId || !state.seenIds.size) return;
  socketSend({ action: 'read', chat_id: chatId, up_to: Math.max(...state.seenIds) });
}
```
- `seenIds` holds the ids of messages drawn in the open chat, so its maximum is the newest one on screen.

## Problems we encountered
- [P-30 · Read receipts covered messages nobody had seen](../problems-and-solutions.md#p-30--read-receipts-covered-messages-nobody-had-seen)
- **I appended three new socket tests to the wrong class.** `ReadReceiptTests` wasn't the last class any more
  (`SocketLifetimeTests` was added after it in session 020), so the new tests became part of `SocketLifetimeTests`.
  GOTCHA already warned about this; the test output's class names showed it. Moved them and listed
  `^class|def test_` to check.
- **A browser test called the REST read view from the test thread.** The view's `async_to_sync` can't run inside
  Playwright's event loop, so it raised, and the view's own `except` logged it. The test passed for the wrong reason.
  It now changes the database directly. New GOTCHA line.

## Engineering decisions and trade-offs
- [Decision 008](../decisions/008-read-up-to-boundary.md): read-up-to boundary over explicit ids.
- **`up_to` required, not optional with "mark everything" as the default:** a default would keep the bug for any
  client that forgot it.
- **Shared functions live in `chats/consumers.py`**, next to `broadcast_message()`, rather than in a new module: the
  same pattern, one place to look.

## What I should remember
- A receipt describes the screen; send how far the screen got.
- Notifications get lost; keep a way to ask for the current state (`peer_read_up_to`).
- A failed notification is not a failed save.
- Check which class a new test landed in.

## Review questions
1. Bob's page shows messages 1–5 when message 6 arrives and Bob's page sends a read just before drawing it. With the
   boundary, what's marked read?
2. Why does the REST read endpoint now broadcast, and what did the sender see before?
3. How does a page that missed a `read` event while reconnecting get its ✓✓?
4. A broadcast fails right after a socket message is saved. What does the sender's page receive, and why does that
   matter?
5. Why is `True` rejected as `up_to`, when Python says `True == 1`?

<details><summary>Answer key</summary>

1. Messages up to 5: the read carries `up_to: 5`, and `mark_read` filters `id <= 5`. Message 6 stays unread until a
   read with `up_to >= 6` is sent after it's drawn.
2. So the sender's ticks update whichever door the reader used. Before, a REST read changed the database but the
   sender's page showed ✓ until a reload.
3. `loadChats()` runs on reconnect and every 45 s; it reads `peer_read_up_to` for the open chat and calls
   `showReadUpTo()`.
4. An echo of its own message, sent directly to its socket. Without it, the page saw no answer (the consumer
   crashed), kept the text, and the user would send a duplicate.
5. `bool` is a subclass of `int` in Python, so `isinstance(True, int)` is true. A boolean is never a sensible message id,
   so `is_message_id()` excludes it explicitly; on REST, DRF's `IntegerField` rejects it.
</details>

## Next steps
- Review and merge this PR.
- PR B: ordering and paging (M-03, M-09, M-10, M-11) with DRF CursorPagination.
