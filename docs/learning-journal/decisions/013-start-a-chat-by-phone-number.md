# 013 · A chat starts from a phone number, not a user id

- **Date:** 2026-10-13 · **Status:** Accepted (chosen by you, T-05, session 029)

## Problem
`POST /chats/` took `{"participant_id": N}`. User ids are sequential (1, 2, 3…), so any account could open a chat
with every user, without knowing anything about them: count up and post. The phone lookup (`GET /users/lookup/`)
was only a convenience in front of that, with its own throttle, so its 20/hour limit protected nothing
([audit SEC-4](../../scaling/01-audit.md)).

## Options considered
1. **(a) Keep "anyone by id"**, limited only by the 30/hour chat throttle (T-03).
2. **(b) Require the phone number.** `POST /chats/ {"phone_number": "..."}`; the lookup endpoint goes away, so
   finding someone and starting a chat are one throttled request.
3. **(c) Message requests.** The recipient must accept before the first message arrives.

## Chosen: option 2 (b)
- You can only start a chat with someone whose number you already know, like a phone's messaging app.
- One door, one throttle: `chat_create`, now **20/hour** (the old lookup limit, the tighter of the two). Misses
  count too, so walking numbers to find accounts costs the same as starting chats.
- Small change: one serializer, one client call, no new model.
- A missing user, someone who blocked you and someone you blocked all get the same **404**, so a block stays
  undetectable. Your own number is a 400 ("You can't start a chat with yourself").

## Disadvantages and limits
- Breaking API change: a client sending `participant_id` now gets a 400. The only client is `assets/app.js`,
  changed in the same commit.
- Someone who knows your number can still message you. That's what option (c) would fix.
- A determined scraper with many accounts can still probe 20 numbers an hour per account; registration is limited
  by IP (5/hour), not by phone ownership (no SMS check).
- `GET /users/<id>/` still shows a profile by id (120/min). It can't start a chat, but it does let someone walk
  names and photos. Unchanged here.

## When another option is better
- **(c) message requests** if spam between strangers appears in real use; it's the plan's next step.
- **(a)** never, for a public app: it makes "message everyone" a loop.
