# 036 · One refresh token, two requests; logout from a stale tab

- **Date:** 2026-10-13 · **Phase:** Stage 1
- **Task:** Codex review of PRs #38–#43, the two High findings (both in T-07's refresh rotation, session 030)
  · **Branch:** `t-07-refresh-single-use`
- **Files:** `accounts/models.py`, `accounts/migrations/0003_loginsession.py`, `accounts/serializers.py`,
  `accounts/views.py`, `root/settings.py`, `accounts/tests.py`, `chats/test_browser.py`, docs
- **Objective:** a refresh token must really work only once, even when two requests bring it at the same moment, and
  "Log out" in any tab must end the login, even when that tab holds an older refresh token than another tab.

## What was done
1. **Read SimpleJWT 5.5.1's code.** A refresh first checks "is this token on the blacklist?" (a `SELECT`), then
   later puts it there with `BlacklistedToken.objects.get_or_create(...)`. When two requests both pass the check, the
   second `get_or_create` finds the row the first one created and simply returns it. Nobody looks at its `created`
   flag, so the second request gets a new token too.
2. **Reproduced finding 1** (two requests, one token):
   - Test `ConcurrentRefreshTests` (Postgres only): two threads send the same token. A `Barrier` holds both just
     after their token passed the checks, so the race happens every run. On the old code: **`[200, 200]`**.
   - Without any hold, against a real Daphne: **20 of 20** pairs of parallel refreshes both succeeded, and both new
     tokens kept working afterwards. Two live logins from one token: a thief keeps one.
3. **Reproduced finding 2** (logout from a stale tab):
   - Server test: log in (R0), refresh (R0 → R1), log out with R0: **401**, and R1 kept working.
   - Browser test, two tabs of one browser: tab A renews; tab B (still holding R0) clicks "Log out": logout
     answered **401**, and A's R1 still renewed.
   - Browser test, logout *during* a refresh: A's refresh reaches the server (R0 → R1) but its answer is held; B logs
     out with R0 meanwhile (**401**); then A receives R1, which still worked.
4. **Fix: a row per login** (`accounts.LoginSession`). See the walkthrough. The login's refresh tokens carry its
   id (`sid`), which every rotation keeps. Refresh swaps the session's one valid token id in a single `UPDATE`;
   logout marks the session ended. SimpleJWT's blacklist app is removed: nothing uses it anymore.
5. **Results:** the 2 server tests and 2 browser tests above fail on the old code and pass now (the browser tests were
   run on the old code with only the tests added). One new guard: a token from before this change (no `sid`) is
   refused. `make test` **170 run, OK (skipped=18)**; real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True`
   **207 OK**; `makemigrations --check` no changes; Ruff 0.16.10 clean.

**Not done:**
- Nothing deletes old `LoginSession` rows yet. It's one row per login (not per refresh, like the blacklist was), so
  it grows slowly; a daily "delete ended or expired" job belongs with the deploy (T-10).
- The old `token_blacklist_*` tables stay in existing databases (removing an app doesn't drop them). Harmless; drop
  them by hand if wanted.
- Everyone signed in before this change has to sign in again once (their tokens have no `sid`).
- Access tokens still live up to 5 minutes after logout (unchanged, decision 014).
- The other three findings of the review (logout throttle, cross-tab lock) are separate branches.

## Concepts

### Race condition: "check, then act"
- **Simple definition:** two requests both *check* a condition ("not used yet?") before either *acts* ("mark it
  used"). Both see "not used yet", so both act.
- **Here:** check = "is the token blacklisted?", act = "blacklist it and issue a new one". The gap between them was
  several queries wide, and in 20 of 20 tries both requests fit inside it.
- **Same lesson as P-27** (8 sockets passed a limit of 5): the check and the act must be one step.

### Compare-and-swap in one `UPDATE`
- **Simple definition:** "change X to the new value, but only if it still has the old value", done by the database as
  one statement, so nothing can happen in between.
- **Here:** `UPDATE accounts_loginsession SET refresh_jti = 'new' WHERE id = 7 AND refresh_jti = 'old' AND ended_at IS NULL`.
  The database tells us how many rows it changed: 1 → this request won; 0 → the token was already spent, or the
  login ended.
- **Why it's safe with two requests at once:** Postgres locks the row for the first `UPDATE`. The second waits, then
  re-checks its `WHERE` against the *new* row, where `refresh_jti` is no longer `'old'`, and changes nothing.

### Login session (`sid`)
- **Simple definition:** one row that stands for "this browser signed in", for as long as it stays signed in.
- **Why we needed it:** the refresh token changes every 5 minutes, so "the token" can't identify the login. Tab B's
  R0 and tab A's R1 are different tokens of the *same* login; the `sid` claim inside both says which login.

## Walkthrough

`accounts/models.py`, starting a login:
```python
def start(self, user):
    token = RefreshToken.for_user(user)
    session = self.create(user=user, refresh_jti=token['jti'], expires_at=datetime_from_epoch(token['exp']))
    token['sid'] = session.pk
    return token
```
- `jti` is the token's unique id (SimpleJWT puts one in every token). The session stores the id of the one refresh
  token that may be used next.
- `token['sid'] = ...` adds a claim. When SimpleJWT rotates the token it keeps every claim except `jti`, `exp` and
  `iat`, so all later tokens of this login carry the same `sid`. The access tokens made from it carry it too (not used
  yet).

`accounts/serializers.py`, refreshing:
```python
presented = self.token_class(attrs['refresh'])
data = super().validate(attrs)  # checks the token and the account, and makes the new pair
renewed = self.token_class(data['refresh'], verify=False)
swapped = LoginSession.objects.filter(
    pk=presented.get('sid'), refresh_jti=presented['jti'], ended_at=None,
).update(refresh_jti=renewed['jti'], expires_at=datetime_from_epoch(renewed['exp']))
if not swapped:
    raise InvalidToken('Token is no longer valid')
```
- `super().validate()` is SimpleJWT's own refresh: signature, expiry, "is the account still active?", then a new
  refresh token. With the blacklist app gone it writes nothing, so a request that loses the swap leaves nothing behind.
- `.update()` returns the number of rows changed. That number *is* the answer: no separate check before it.
- `verify=False` on `renewed`: we made that token a line earlier, so there's nothing to verify.

`accounts/serializers.py`, logging out:
```python
token = RefreshToken(attrs['refresh'])
LoginSession.objects.filter(pk=token.get('sid'), ended_at=None).update(ended_at=timezone.now())
```
- `RefreshToken(...)` still checks the signature and the expiry, so only a real token of ours can end a login.
- It does **not** check whether the token is the session's current one: tab B's older R0 is still proof enough.
  Someone holding an old copy can sign the user out, but can't sign in.

The browser test for "logout during a refresh" holds the *answer*, not the request:
```python
def renew_but_hold_the_answer(route):
    held.append((route, route.fetch()))   # the server has swapped R0 -> R1 now
```
`route.fetch()` sends the request to the real server and returns its response without giving it to the page. Later,
`route.fulfill(response=answer)` delivers it. That recreates "the server already renewed, the tab doesn't know yet".

## Problems
- **Two parallel refreshes both succeeded** → [P-39](../problems-and-solutions.md#p-39--one-refresh-token-two-parallel-requests-two-new-tokens).
- **Logout with a stale token was refused** → [P-40](../problems-and-solutions.md#p-40--logout-from-a-tab-with-an-older-token-didnt-end-the-login).
- **One full run had 2 errors** in `SessionLifecycleTests` (`test_a_refresh_that_fails_on_the_network_retries_instead_of_stalling`,
  `test_a_send_waiting_at_logout_does_not_block_the_next_account`). Both passed alone, the next full run was 207 OK,
  and the browser module then passed 3 runs in a row (34 OK each). The error text wasn't kept, so the cause is unknown
  (*Hypothesis:* timing on a busy Mac). Watch for it in CI.
- **A test run hung for 5 minutes.** An interrupted run left `test_onlinechat` behind, and the next run asked
  "delete it? (yes/no)" and waited for an answer that never came. Use `manage.py test --noinput` in scripts.

## Decisions
- A session row with compare-and-swap instead of SimpleJWT's blacklist: [decision 016](../decisions/016-login-sessions.md).
  It updates decision 014's "Chosen: 1".

## What I should remember
- `get_or_create` is not "claim it once": the loser gets the existing row back, with `created=False`.
- If the check and the act are two statements, two requests can both pass the check. Make the act carry the check
  (a `WHERE` on the old value) and look at the row count.
- A token that changes on every refresh can't name a login. Give the login its own id.
- Hold a race open on purpose (a `Barrier`, a held response) so the test fails every time, not now and then.

## Review questions
1. Why did two requests with the same refresh token both get a new one on the old code?
2. In `SessionRefreshSerializer`, what makes the second of two simultaneous requests fail?
3. Why does logout accept a refresh token that has already been renewed? What can someone do with an old stolen copy?
4. What does `sid` stand for, and why does it survive rotation?
5. Why did the browser test hold the refresh *answer* (`route.fetch()`) instead of the request?
6. What happens to someone who was signed in before this change was deployed?

<details><summary>Answer key</summary>

1. Each request checked "is it blacklisted?" first, and both saw "no". Then each called `get_or_create` to blacklist
   it; the second just got back the row the first had created, and no one checked `created`. Both went on to issue
   new tokens.
2. The `UPDATE ... WHERE refresh_jti = <presented>` . The first request changes the row to the new id. The second waits
   for the row lock, then re-checks its `WHERE` on the changed row, matches nothing, and gets 0: `InvalidToken`, 401.
3. Because another tab may have renewed it: the stale tab's token is still a genuine token of that login. With an old
   copy, someone can only end the login (sign the user out); they can't renew it.
4. Session id: the id of the `LoginSession` row. SimpleJWT copies every claim except `jti`, `exp` and `iat` into the
   rotated token.
5. Holding the request would mean the server hasn't renewed yet, so logout would come first: the easy case. Holding
   the answer recreates the hard one: the server already swapped R0 for R1, but the page doesn't know R1 yet when the
   other tab logs out.
6. Their refresh token has no `sid`, so the next refresh gets 401 and they sign in again once. Their access token
   works until it expires (≤ 5 minutes).
</details>

## Next steps
- Logout shares the refresh throttle (finding: logout blocked by 429), then the cross-tab refresh lock.
- With T-10: a daily job deleting ended and expired `LoginSession` rows.
