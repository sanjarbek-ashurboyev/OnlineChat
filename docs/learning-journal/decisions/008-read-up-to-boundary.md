# 008 · Read receipts carry a read-up-to boundary

- **Date:** 2026-10-11 · **Status:** Accepted (chosen by you in session 022)

## Problem
Codex audit M-06, M-07, M-08: a read marked every unread message in the chat, including ones that arrived after the
screen was drawn; the receiving page ticked every outgoing message; REST reads told nobody; and a receipt lost while
offline was never repaired.

## Options considered
1. **Read-up-to boundary:** the client sends the newest message id on screen; the server marks up to it and
   broadcasts that id. The chat list adds `peer_read_up_to` (the newest of my messages the other person has read).
2. **Explicit ids:** the client sends the list of message ids it displayed; the server marks exactly those.

## Chosen: option 1
- One number per read, whatever the number of messages; frames stay small.
- Messages in a chat are shown in id order, so "everything up to the newest shown" is what the screen means.
- `peer_read_up_to` is one aggregate in the chat-list query that already joins messages, and it doubles as the repair
  for any receipt that went missing.

## Disadvantages and limits
- **`up_to` is now required** on the socket's `read` action and the REST read endpoint (400 / error without it). Our
  only client was updated in the same PR; another client would break.
- It assumes the screen shows a contiguous run of messages up to `up_to`. A gap in the middle (a message that never
  arrived live) would be marked read anyway. Closing that gap is M-03, in the next PR.
- The chat list does one more aggregate (`Max`) over the messages join; measure it together with audit risk R-04.

## When another option is better
- **Explicit ids** for "read" states on non-contiguous views, e.g. a search result page or threaded replies.
