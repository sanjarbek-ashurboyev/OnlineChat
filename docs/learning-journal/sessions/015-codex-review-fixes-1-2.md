# 015 · Codex review: disabled accounts on WebSockets, unlimited REST sends

- **Date:** 2026-10-11 · **Phase:** Stage 0
- **Task:** findings #1 and #2 from a review by OpenAI Codex, not in the backlog · **Branch:** `fix-ws-inactive-and-rest-throttle`
- **Files:** `chats/middleware.py`, `chats/views.py`, `root/settings.py`, `chats/test_consumers.py`, `chats/tests.py`, docs
- **Objective:** a disabled account can't use the socket, and sending over REST has a limit like the socket does.

## Before we started
- Added `AGENTS.md` (PR #24) so Codex follows the same rules as Claude Code. Codex then reviewed the whole project
  and reported 9 findings. Claude checked each one against the code: all 9 were real (see the list at the end).
- This session fixes the two security ones. Branched from an up-to-date `main` (`e92f4da`).

## What we accomplished
1. **Wrote three tests first:**
   - `test_a_disabled_account_is_refused_even_with_a_valid_token` (`chats/test_consumers.py`): **errored**. The
     socket was accepted, so the test timed out waiting for the close.
   - `test_sending_is_limited_to_60_a_minute_but_reading_is_not` (`chats/tests.py`): **failed**, `201 != 429`.
   - `test_a_disabled_account_cannot_use_its_token` (`chats/tests.py`): **passed straight away**. That confirmed
     the claim that REST was already safe, and it now guards that behaviour.
2. **Fix #1** (`chats/middleware.py`): the socket's JWT middleware looks the user up with `is_active=True`.
   A disabled user isn't found, becomes `AnonymousUser`, and the consumer closes with 4401.
3. **Fix #2** (`chats/views.py`, `root/settings.py`): `POST /chats/<id>/messages/` has a `message_send` scope,
   **60/min per user**. Reading history is not limited.
4. **Results:** `make test` → **83 tests, OK (2 skipped)**. `ruff check .` (0.16.10) → clean.

**Not done:**
- **Real Postgres + Redis suite not run locally.** Docker wasn't running. CI's `test-postgres-redis` job covers it.
- **The limit isn't shared between REST and the socket.** A user can send 60/min over REST *and* 1/s per socket.
  Each path now has a limit, which closes the "unlimited" hole. One shared per-user limit would need the socket's
  bucket moved into Redis, which is a bigger change.
- **An open socket isn't kicked when the account is disabled.** The check runs at connect. Disabling someone
  stops their *next* connection. Closing live sockets would need an admin action that sends them a close event.
- Findings #3–#9 are still open.

## Concepts I learned

### `is_active`, Django's "account disabled" switch
- **Simple definition:** a `True`/`False` field on every Django user. `False` means "this account exists, but may
  not sign in". Admins use it instead of deleting a user, so their messages stay.
- **The trap:** a JWT is checked by its **signature and expiry**, not by looking at the database. A token issued
  before the account was disabled is still valid. Something must look the user up and check `is_active`.
- SimpleJWT's REST authentication does that check for us. Our own WebSocket middleware didn't.

### Every path to an action needs the same rule
- **Simple definition:** if the app can do something in two ways (send over REST *or* over the socket), a
  protection on one way is no protection. An attacker uses the other one.
- **Everyday example:** locking the front door but leaving the back door open.
- Both bugs are this mistake. Auth was checked on the REST door, not the socket door. The rate limit was on the
  socket door, not the REST door.

## Important code walkthrough

### `chats/middleware.py`
```python
try:
    # is_active: a disabled account's unexpired token must stop working, as it does for REST.
    return User.objects.get(pk=token['user_id'], is_active=True)
except (KeyError, User.DoesNotExist):
    return AnonymousUser()
```
- Adding `is_active=True` to the lookup turns "disabled" into "not found". The existing `except` already handles
  "not found", so there's no new branch to get wrong.

### `chats/views.py`
```python
throttle_scope = 'message_send'

def get_throttles(self):
    # Only sending is limited; reading history and catching up after a reconnect are not.
    return [ScopedRateThrottle()] if self.request.method == 'POST' else []
```
- The same pattern as `ChatListCreateAPIView` (T-03). One view serves both `GET` (history) and `POST` (send), and
  only `POST` should be limited. A reconnecting client may fetch several pages of history at once (T-09).
- **Why 60/min:** the socket allows a sustained 1 message per second. 60/min is the same rate, so neither path
  is looser than the other.

## Problems we encountered
- [P-20 · Two doors, one lock: auth and rate limits only on one transport](../problems-and-solutions.md#p-20--two-doors-one-lock-auth-and-rate-limits-only-on-one-transport)

## Engineering decisions and trade-offs
- **A separate limit per path rather than one shared limit:** small and testable now. A shared limit means moving
  the socket's token bucket into Redis (one round trip per frame). Worth it only if someone actually abuses both
  paths at once.
- **Check `is_active` at connect only:** simple, and matches REST, which also checks per request. A socket is one
  long request, so its check happens once. Kicking live sockets is a separate feature.

## What I should remember
- A valid JWT doesn't mean an allowed user. Signature and expiry say nothing about whether the account is still active.
- When a rule protects an action, list every way to reach that action, and test each one.
- A test that passes on the first run isn't wasted. It documents and guards behaviour you were relying on.
- A second reviewer (another person, or another model) finds things the first one missed.

## Review questions
1. A user is disabled at 10:00. Their access token expires at 10:20. Before this fix, what could they do at 10:05?
2. Why is adding `is_active=True` to the `get()` enough, without an `if` statement?
3. Why does `get_throttles` return an empty list for `GET`?
4. Code reading: the throttle test calls `cache.clear()` at the start and via `addCleanup`. Why both?
5. After this fix, what is the most messages per minute one user can send? (They have 5 tabs open.)
6. Why didn't `test_a_disabled_account_cannot_use_its_token` fail first, and why keep it?

<details><summary>Answer key</summary>

1. REST: nothing, because SimpleJWT checks `is_active`. WebSocket: open a socket with the token and keep sending
   messages, receiving messages and showing as online.
2. A disabled user then raises `User.DoesNotExist`, which the existing `except` already turns into `AnonymousUser`,
   and the consumer already refuses that with 4401.
3. `GET` reads history. After a reconnect the client fetches what it missed (T-09), and limiting that would break
   recovery. Only sending creates rows and broadcasts.
4. The throttle counts live in the cache, which a test's database rollback doesn't reset. Clearing first protects this
   test from earlier ones; clearing after protects later tests from this one's 60 sends.
5. 60 over REST, plus about 60 per socket (1/s after a burst of 10) × 5 sockets: roughly 360. Each path is limited,
   but not the total. That's the "not shared" trade-off above.
6. REST was already correct (SimpleJWT checks `is_active`). The test proves Codex's claim and fails if someone ever
   swaps in authentication that skips the check.
</details>

## Codex's other findings (still open)
3. Switching chats while history loads can show chat A's messages in chat B (`assets/app.js`, `loadHistory`).
4. "Load older" renders each older page in reverse order.
5. The sidebar ignores pagination: chats after the first 50 are unreachable.
6. A rejected message clears the composer, so the text is lost.
7. Sockets lose their group membership after 24 h (`group_expiry`) and stop receiving messages.
8. The load tester can report "healthy" without measurements. Session 014's numbers need a rerun after it's fixed.
9. Marking read over REST doesn't notify the sender's open sockets.

## Next steps
- Review and merge this PR.
- Frontend fixes #3–#6, with tests. Then fix the load tester (#8) and rerun the baseline.
