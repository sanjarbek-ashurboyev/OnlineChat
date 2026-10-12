# 010 · Someone who blocked you: keep the chat, blank their details

- **Date:** 2026-10-11 · **Status:** Accepted (chosen by you in session 024)

## Problem
Codex audit M-14: `GET /users/<id>/` answers 404 to someone the user has blocked, but the chat list still returned
the blocker's photo, online status and last seen. The privacy rule held on one endpoint only.

## Options considered
1. **Keep the chat, blank `avatar`, `is_online` and `last_seen`; keep `id` and `display_name`.** As Telegram does.
2. **Same, and blank the name too** (the app shows "Unnamed").
3. **Remove the chat** from the blocked person's list.

## Chosen: option 1
- The history is the blocked person's conversation too; removing it (option 3) takes it away, and makes the block
  obvious.
- Blank details look like someone who never set a photo and hasn't been online, so the block stays undetectable, as
  on the lookup and profile endpoints.
- The name is what the blocked person already knew when they chatted; blanking it (option 2) makes the chat hard to
  recognise for little gain.

## Disadvantages and limits
- A name change the blocker makes after blocking still shows.
- Only the blocker's own block hides them. Someone *you* blocked still shows their details, matching the profile
  endpoint.
- No API creates blocks yet, so today this matters only for blocks made in the database.

## When another option is better
- **Option 2** if names become sensitive (e.g. a real-name policy).
- **Option 3** if a "delete for both" or "report and block" feature is added; that's a different promise to the user.
