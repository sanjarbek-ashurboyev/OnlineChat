# 007 · When a message's echo doesn't come, check the history

- **Date:** 2026-10-11 · **Status:** Accepted

## Problem
Codex audit H-06: the browser sends one message at a time and waits for its echo. If the echo was lost
(the channel layer drops notifications sometimes) or the connection silently died, the page waited forever,
and no message could be sent in any chat until a reload.

## Options considered
1. **Timeout, then look in the history:** after 10 s, fetch messages after the last one shown. Our message is
   there → it was saved, show it. Not there → keep the text and tell the user.
2. **Idempotency key:** the browser gives each message a random id; the server stores it with a unique
   constraint and ignores a second message with the same id. The page can then resend blindly after a timeout.
3. **Timeout only:** after 10 s, stop waiting and let the user resend.

## Chosen: option 1
- No server or database change; it uses the gap-fetch endpoint that already exists (`?after=`).
- It answers the question the user has ("did it go through?") instead of guessing.
- Option 3 creates duplicates whenever the echo, not the message, was lost.

## Disadvantages and limits
- **Matching is by sender and text.** If you sent the same text twice within the window, the check can't tell them
  apart. Rare for chat, but real.
- **A very slow server** (saves after 10 s) shows "may not have been sent" for a message that then appears. The text
  stays in the composer, so a user could send it twice.
- One extra request per lost echo; nothing in the normal case.

## When another option is better
- **Option 2** when duplicates are costly (payments, orders), or when the client should retry on its own, e.g. a
  mobile app with an offline queue. It needs a migration (`client_id` with a unique constraint per sender).
