# 029 · T-05: a chat starts from a phone number, not a user id

- **Date:** 2026-10-13 · **Phase:** Stage 0 (last open product decision)
- **Task:** T-05, who can start a chat ([backlog](../../scaling/03-operations.md), audit SEC-4) · **Branch:** `t-05-chat-by-phone`,
  stacked on `t-12-stage0-baseline` (PR #38), so merge #38 first
- **Files:** `chats/serializers.py`, `accounts/views.py`, `accounts/urls.py`, `accounts/serializers.py`, `root/settings.py`,
  `root/settings_test.py`, `assets/app.js`, `chats/tests.py`, `chats/test_chat_refresh.py`, `accounts/tests.py`, docs
- **Objective:** nobody can open a chat with a stranger by counting up user ids.

## What was done
1. **Decision** (yours): option (b) from the plan, "phone number required"
   ([decision 013](../decisions/013-start-a-chat-by-phone-number.md)).
2. **Tests first.** `StartChatTests` now starts chats with `{"phone_number": ...}` and has new cases: local and
   international formats, the phone number isn't revealed, a user id alone is refused, a block **either way** looks
   like a missing user (404), and 20 requests an hour, misses included. The `UserLookupTests` cases moved here.
   On the old code: **8 failures and 2 errors**. Three cases (yourself, bad number, no token) already passed,
   because the old code answered 400/401 for different reasons. They're guards, not proof.
3. **Code.**
   - `ChatCreateSerializer` takes `phone_number`, parses it like the lookup did (`to_python(..., region='UZ')`), and
     returns the user it found.
   - `GET /users/lookup/` is gone, with `UserLookupAPIView`, `UserLookupSerializer` and the `user_lookup` rate.
   - `chat_create` went from 30 to **20/hour**, so probing numbers isn't faster than the old lookup allowed.
   - `app.js`: the search form makes one request instead of two.
4. **Results:**
   - `make test`: **152 run, OK (14 skipped)**.
   - Real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True`: **183 tests, OK**, including the browser test that
     starts a chat from the phone form.
   - `ruff check .` (0.16.10): clean.

**Not done:**
- Message requests (option c). Someone who knows your number can still write to you.
- `GET /users/<id>/` still shows a profile by id (limited to 120/min). It can't start a chat any more.
- The browser test is still called `test_lookup_opened_chat_...`. The form is still a lookup from the user's point
  of view, so the name stays.

## Concepts

### Enumeration
- **Simple definition:** finding out what exists by trying values one after another. With ids 1, 2, 3…, "try every
  id" finds every user.
- **Why it matters here:** `POST /chats/ {"participant_id": 7}` worked for any 7. A loop could open a chat with every
  account and send each of them spam.
- **The fix isn't only a limit:** the request must need something you can't guess. A phone number is 9 digits per
  country, and you'd have to already know it. The throttle then caps how fast anyone can guess.

### One door, one lock (again)
The lookup endpoint had a 20/hour limit, but it wasn't the only way to reach the action. Chats started from ids,
so the limit guarded a side door. Same lesson as [P-20](../problems-and-solutions.md#p-20--two-doors-one-lock-auth-and-rate-limits-only-on-one-transport):
put the check on the **action**, not on one way of getting there.

### Not leaking through error codes
A missing user, someone who blocked you, and someone you blocked all answer the same **404** with the same text.
If "blocked" gave 403 and "missing" 404, the difference itself would tell you that you were blocked.

## Walkthrough: `chats/serializers.py`
```python
class ChatCreateSerializer(Serializer):
    phone_number = CharField(write_only=True, help_text='E.164 or local UZ format.')

    def validate_phone_number(self, value):
        me = self.context['request'].user
        number = to_python(value, region='UZ')          # "90 123 45 02" → +998901234502
        if not number or not number.is_valid():
            raise ValidationError('Enter a valid phone number.')        # 400
        if number == me.phone_number:
            raise ValidationError("You can't start a chat with yourself.")  # 400

        other = User.objects.filter(phone_number=number).first()
        if other is None or Block.objects.filter(
            Q(blocker=other, blocked=me) | Q(blocker=me, blocked=other)
        ).exists():
            raise NotFound('Nobody is registered with that number.')    # 404, same for both
        return other
```
- A `validate_<field>` method can return a different value than it received. Here it returns the `User`, so
  `create()` gets `validated_data['phone_number']` as a user and doesn't look them up a second time.
- `ValidationError` becomes a 400 with `{"phone_number": [...]}`. `NotFound` isn't a validation error, so DRF doesn't
  catch it as one: it becomes a 404 with `{"detail": ...}`. The client shows a friendly text on 404.
- The throttle runs before any of this, in the view, so a request for a number that doesn't exist still uses up
  one of the 20.

## Problems
None in the code. One process note: PR #38 (docs) and this branch both add a row in the same place in
`progress.md`, so this branch is stacked on #38 to avoid a merge conflict.

## Decisions
- [Decision 013](../decisions/013-start-a-chat-by-phone-number.md): phone number required; 404 for missing and blocked.
- 20/hour, not 30: the merged endpoint inherits the tighter of the two old limits.

## What I should remember
- A limit on one way to do something protects nothing if there's another way. Limit the action.
- Make the request need something an attacker doesn't have (the number), not just something countable (an id).
- Same answer for "missing" and "blocked", or the answer leaks the block.

## Review questions
1. The lookup endpoint already had a 20/hour limit. Why didn't that stop someone messaging every user?
2. Why does a request for a number nobody owns still count towards the 20?
3. What would a scraper learn if a block returned 403 and a missing user 404?
4. Why does `validate_phone_number` return a `User` and not the number?
5. What can a stranger who knows your number still do, and which option would stop it?

<details><summary>Answer key</summary>

1. Starting a chat didn't need the lookup: `POST /chats/` took any user id, and ids are sequential. The limit was on
   a side door.
2. DRF checks throttles before the view runs, on every request. That's what we want: a scraper's requests are mostly
   misses, and they must cost the same as hits.
3. Which accounts exist and have blocked them, separately from which numbers have no account at all. The block
   itself would be detectable.
4. `create()` needs the user. Returning it from validation avoids a second query, and keeps "find the user" and
   "check the block" in one place.
5. Start a chat and send messages. Option (c), message requests, would make the first message wait for acceptance.
</details>

## Next steps
- T-07: refresh token rotation and server-side logout.
- `/readyz` (T-21 / T-12 step 3).
- If spam appears in real use: message requests (option c).
