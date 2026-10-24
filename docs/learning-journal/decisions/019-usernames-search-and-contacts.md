# 019 · Usernames with prefix search; contacts are added by phone number

- **Date:** 2026-10-24 · **Status:** Accepted (chosen by you, 2026-10-24) · Extends [decision 013](013-start-a-chat-by-phone-number.md)

## Problem
Today the only way to reach someone is their phone number (decision 013): you can't find a person you met
online without asking for their number, and every new chat means sharing it. We want Telegram's model:
- people **find each other by username**, and can search for one by its first letters;
- the phone number is still how you add someone you already know, as a **contact** with a name you choose.

## Options considered
**Username: required or optional**
1. **Required** at sign-up (and a forced step for existing users).
2. **Optional:** set it in Settings; without one, nobody can find you by search.

**Search**
1. **Exact match:** type the whole username, get one person or nothing. Can't be used to list users.
2. **Prefix search:** "ale" lists `alex`, `alena_k`… Friendlier, but it can list every user who has a username.

## Chosen: optional username, prefix search
- A username is **opt-in**. Setting one means "people may find me", like Telegram. Users without one are only
  reachable by phone, as today. Sign-up doesn't change; existing accounts need nothing.
- Prefix search, with limits that make listing slow and show little:
  - the query needs **at least 3 characters** (after trimming `@` and lowercasing);
  - **20 results at most**, the exact match first, then shorter usernames, then A–Z;
  - a result is `id`, `username`, `display_name`, `avatar`: **no presence or last seen** (that stays for chats
    and contacts);
  - someone who blocked you, or whom you blocked, is never in your results (a block stays undetectable, as in 013);
  - its own throttle, `user_search` **60/min**. The client waits ~300 ms after typing stops, so typing a name
    costs one or two requests.

### Username rules
- 5–32 characters, `a–z`, `0–9`, `_`; starts with a letter, doesn't end with `_`, no `__`.
- Stored **lowercase** and unique (`alex` and `Alex` are the same name). A `CharField(unique=True, null=True)`:
  on Postgres Django also creates a `varchar_pattern_ops` index, so `username__startswith` uses an index.
- A reserved list can't be taken: `admin`, `support`, `onlinechat`, `settings`, `api`, `help`, `security`…
- Changing it frees the old name at once; removing it (empty) makes you unfindable again.
- The model keeps `USERNAME_FIELD = 'phone_number'`: **login stays by phone and password.**

### Starting a chat
`POST /chats/` takes **exactly one** of:
- `username`: someone found by search;
- `phone_number`: as today (decision 013);
- `contact_id`: one of your own contacts (ids of your own rows, so this can't walk other users).

Never a user id: ids are sequential, so that would undo decision 013. A missing user, a block either way and a
user without that username all get the same 404.

### Contacts
- New model `Contact(owner, user, name, created_at)`, unique per `(owner, user)`.
- `POST /contacts/ {phone_number, name}` → 201, or 404 if nobody has that number (blocks: 404 too).
  `GET /contacts/`, `PATCH /contacts/<id>/` (rename), `DELETE /contacts/<id>/`.
- Every request that looks up a **phone number** (adding a contact, starting a chat by phone) shares one
  throttle, `phone_lookup` **20/hour**, which replaces `chat_create` for that path. Otherwise contacts would be a
  second door for probing numbers.
- **Your contact name wins:** the chat list, chat header and search results show your name for them, not theirs.
  The chat list builds an `owner → name` map in one query, like `blocked_by`.
- You see your contacts' phone numbers (you typed them). Nobody else sees anyone's number; that's already true
  (`PublicUserSerializer` has no phone field) and stays so.
- Adding someone as a contact doesn't tell them, and doesn't start a chat.

## Disadvantages and limits
- **Prefix search can list users who set a username.** At 60/min and 20 results, walking all 3-letter prefixes
  (~35,000) takes one account ~10 hours, and many accounts go faster (sign-up is limited by IP, not phone, as in
  013). We accept it because a username is public by choice, and results show no presence or phone.
- Adding a contact by phone still tells you whether a number has an account. Same as starting a chat today; the
  shared 20/hour throttle keeps the cost the same.
- A freed username can be taken by someone else at once, so an old link or a friend's memory can point to a
  stranger. Telegram has the same problem.
- No address-book upload (match my phone's contacts): one number at a time.

## When another option is better
- **Exact match** if scraping shows up in the metrics (`user_search` 429s from many accounts): the API stays
  the same, only the query and the minimum length change.
- **Message requests** (013's option c) if strangers who find you by username start spamming. Search makes
  that more likely than phone numbers did.
- **A hold on freed usernames** (e.g. 14 days) if impersonation through freed names happens.

## Tasks
1. **U-01 · Username:** model field + migration, validation and reserved list, `username` in the profile
   (editable) and public serializers, tests. The Settings field comes with F-06.
2. **U-02 · Search and start by username:** `GET /users/search/?q=`, `user_search` throttle, `POST /chats/`
   with `username` / `contact_id`, the search box's "Global search" section under the local chat filter.
3. **U-03 · Contacts:** model, API, shared `phone_lookup` throttle, contact names in the chat list and header,
   the contacts screen and "Add contact".
