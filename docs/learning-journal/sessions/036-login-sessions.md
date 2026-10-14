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
- ~~The old `token_blacklist_*` tables stay in existing databases (removing an app doesn't drop them). Harmless; drop
  them by hand if wanted.~~ Not harmless: they made deleting a user fail. Fixed in the follow-up below (P-42).
- Everyone signed in before this change has to sign in again once (their tokens have no `sid`).
- Access tokens still live up to 5 minutes after logout (unchanged, decision 014).
- The other findings of the review: the logout throttle is a separate branch; the cross-tab lock came with the
  follow-up below.

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

---

# Follow-up · Codex review of PR #46, round 1

- **Date:** 2026-10-14 · **Branch:** `t-07-refresh-single-use` (same PR, #46)
- **Files:** `assets/app.js`, `accounts/migrations/0004_drop_token_blacklist_tables.py`, `accounts/tests.py`,
  `chats/test_browser.py`, `docs/scaling/03-operations.md`, docs
- **Objective:** Codex confirmed the fixes above, then reproduced two new Medium bugs, both caused by this PR, and
  asked for a deploy note. Reproduce each first, then fix.

## What was done
1. **Reproduced "a tab that loses a refresh race ends the winner's login"** with two browser tests (two tabs of one
   browser, both holding R0). Tab A's refresh reaches the server (R0 → R1) but the test holds its answer; then tab B
   needs a new token too (`state.access = 'expired'; start()`, what a page load does), and the server refuses R0.
   - On the old code: B sent `POST /auth/logout/`, and the login ended, R1 included. Failures:
     `401 != 3` (B signed out) and `[<Request .../auth/logout/>] != []`.
2. **Fixed it in `assets/app.js`**, in two parts:
   - Renewals take turns across tabs under a Web Lock, and a tab first takes a newer token another tab saved
     (`adoptStoredToken()`). So B waits while A renews, then renews with A's R1 and stays signed in.
   - A refused refresh token now calls `signOut()` (this tab only). Only the "Log out" button calls `logout()`, which
     also ends the login on the server. This covers browsers without `navigator.locks`, where the race can still be
     lost: B signs itself out, A keeps working.
3. **Reproduced "deleting a user fails"** two ways:
   - On a copy of the dev database (made with `CREATE DATABASE ... TEMPLATE onlinechat`; it still had the real
     blacklist tables from `main`, with 100 old rows): one row pointing at a user, then `user.delete()` →
     `IntegrityError ... violates foreign key constraint "token_blacklist_outs_user_id_83bc629a_fk_accounts_"`.
     (A first try on the dev database itself ran in a transaction that was rolled back, so nothing changed there.)
   - Test `OldBlacklistTablesTests`: builds the two old tables by hand with the same foreign keys, adds a blacklisted
     token of a user, deletes the user. Failed on SQLite and on Postgres with the same `IntegrityError`.
4. **Fixed it with migration `accounts.0004`**: drops both tables if they exist and forgets the app's migrations.
   Then on a new copy of the dev database: migrate → the user deletes, no blacklist tables, no migration records.
5. **Rehearsed a rollback** on a copy of the dev database, with `main`'s code in a temporary worktree: logged in,
   refreshed and logged out with the new code; went back (`migrate accounts 0002`, then the old code's `migrate`,
   which built the blacklist tables again, empty); the old code then accepted both the rotated-away token and the
   logged-out one (**200, 200**). With a new `DJANGO_SECRET_KEY`: **401, 401**. Rolling forward again re-applied 0003
   and 0004. Written down as the rollback steps under T-07 in `docs/scaling/03-operations.md`.
6. **Results:** the 2 browser tests and the migration test fail on the old code and pass now. `make test`
   **171 run, OK (skipped=18)** (210 found); real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True` **210 OK**
   (36 browser tests); `makemigrations --check` no changes; Ruff 0.16.10 clean.

**Not done:**
- The losing tab still signs itself out in browsers without `navigator.locks` (old browsers, or plain `http://` on
  an address other than `localhost`, where the browser doesn't offer it). The login survives; that tab signs in again.
- The test builds the old tables by hand, not with SimpleJWT's own migrations: once the app is out of
  `INSTALLED_APPS`, SimpleJWT makes its models abstract, so they can't be created. The real tables were covered by the
  dev-database copy, by hand, not in CI.
- The logout-throttle branch (`t-07-logout-throttle`) also changes `logout()` in `app.js`; it will need a rebase onto
  this.

## Concepts

### Web Locks (`navigator.locks`)
- **Simple definition:** a named lock that all tabs of one site share. `navigator.locks.request('refresh-token', fn)`
  waits until no other tab holds `refresh-token`, runs `fn`, and releases the lock when `fn`'s promise settles.
- **Why here:** `localStorage` is shared between tabs, but each tab renews on its own. Without turns, two tabs can
  send the same refresh token at once, and one is refused.
- **Catch:** the lock is released only when `fn`'s promise settles. Our `dropped()` (a promise that never settles,
  used to drop answers after logout) must never be returned inside the lock, or no tab could renew again. So
  `spendRefreshToken()` returns `false` instead, and `renewTokens()` drops the answer *after* the lock.
- **Where it's missing:** only "secure contexts" have it: `https://`, or `http://localhost`.

### Removing a Django app doesn't remove its tables
- **Simple definition:** `INSTALLED_APPS` tells Django which models exist. Taking an app out of it changes what
  Django *knows*, not what the *database* has.
- **Why it broke a delete:** Django deletes a user's related rows itself (in Python) before the user, but only for
  models it knows. The forgotten table still had a foreign key to `accounts_user`, so Postgres refused the delete.
- **How it's cleaned up:** a `RunPython` migration (a migration that runs a Python function) drops the tables and
  deletes the app's rows from `django_migrations`, Django's list of applied migrations.

## Walkthrough

`assets/app.js`, renewing:
```js
async function renewTokens() {
  const session = state.session;
  const work = () => (session === state.session ? spendRefreshToken() : false);
  const renewed = await (navigator.locks ? navigator.locks.request('refresh-token', work) : work());
  if (session !== state.session) return dropped();
  return renewed;
}
```
- `work` checks the session again *inside* the lock: the user may have signed out while this tab waited for it.
- Without `navigator.locks` it just runs `work()`, as before.
- `dropped()` is outside the lock (see the catch above).

```js
async function spendRefreshToken() {
  adoptStoredToken();
  if (!state.refresh) return false;
  ...
  if (res.status === 400 || res.status === 401) {
    if (session === state.session && adoptStoredToken()) return spendRefreshToken();
    return false;
  }
```
- `adoptStoredToken()` first: the tab before us may have saved a newer token while we waited. It's only taken if it
  belongs to the same user (`tokenUser()`), as before.
- After a refusal it tries once more with a newer stored token: without the lock, another tab may still win.

`assets/app.js`, the two ways out:
```js
function logout() {          // the "Log out" button
  if (state.refresh) fetch(`${API}/auth/logout/`, { ... });
  signOut();
}
```
`signOut()` is everything `logout()` did before, minus the request. `start()` (on a 401) and the socket's 4401
handler (when the renewal is refused) now call `signOut()`.

`accounts/migrations/0004_drop_token_blacklist_tables.py`:
```python
def drop_blacklist_tables(apps, schema_editor):
    existing = set(schema_editor.connection.introspection.table_names())
    for table in TABLES:
        if table in existing:
            schema_editor.execute(f'DROP TABLE {schema_editor.quote_name(table)}')
    MigrationRecorder(schema_editor.connection).migration_qs.filter(app='token_blacklist').delete()
```
- `TABLES` lists `blacklistedtoken` first: it points at `outstandingtoken`, so it has to go first.
- `if table in existing`: new databases (CI, a fresh install) never had the tables.
- Deleting the `django_migrations` rows matters for a rollback: the old code's `migrate` then sees the blacklist's
  migrations as not applied and builds the tables again. Backwards, the migration does nothing (`RunPython.noop`).

## Problems
- **A tab that lost a refresh race ended the other tab's login** → [P-43](../problems-and-solutions.md#p-43--a-tab-that-lost-a-refresh-race-ended-the-other-tabs-login).
- **Deleting a user failed after the blacklist app was removed** → [P-42](../problems-and-solutions.md#p-42--after-the-blacklist-app-was-removed-deleting-a-user-failed).
- **The first test tried to install the blacklist app for a moment** (`override_settings(INSTALLED_APPS=...)`) to
  build the real tables: `ImproperlyConfigured: The model OutstandingToken is abstract`. SimpleJWT decides "abstract"
  once, when its models module is first imported. Switched to building the tables by hand.
- **The rollback rehearsal first printed nothing for the token checks.** The script's `APIClient()` used the host
  `testserver`, which `ALLOWED_HOSTS` refuses (an HTML 400, not a DRF answer). `APIClient(SERVER_NAME='localhost')`
  fixed it. Also, `main`'s code in a fresh worktree had no `.env`; it was linked in for the rehearsal and removed after.

## Decisions
- Who may end a login: only the "Log out" button; a refused refresh token signs out one tab. Added to
  [decision 016](../decisions/016-login-sessions.md#update-codex-review-of-46-who-may-end-a-login).

## What I should remember
- Making an action stronger changes every place that calls it. `logout()` started ending every tab's login, and two
  of its three callers were automatic.
- A Web Lock is held until the callback's promise settles. Never return a promise that never settles inside it.
- Removing an app from `INSTALLED_APPS` leaves its tables. Clean up with a migration, and test the upgrade on a
  database the previous release migrated.
- A rollback can need more than the old code: here, a migration back and a new signing key. Rehearse it.

## Review questions
1. In the lost race, why was tab B's refresh token refused, and why did B's sign-out end A's login too?
2. What does `navigator.locks.request('refresh-token', work)` guarantee, and when is the lock released?
3. Why does `spendRefreshToken()` return `false` instead of `dropped()` when the user signed out meanwhile?
4. Why doesn't the automatic sign-out end the login on the server, even though a refused token could mean theft?
5. Why did every test pass while deleting a user failed on a real database?
6. Why does migration 0004 also delete the `token_blacklist` rows from `django_migrations`?
7. After rolling back to the blacklist code, why must `DJANGO_SECRET_KEY` change?

<details><summary>Answer key</summary>

1. A's refresh had already swapped R0 for R1 on the server, so R0 was spent. B signed out with `logout()`, which sends
   R0 to `/auth/logout/`; since P-40 that ends the whole login, whichever token is sent, and R1 belongs to that login.
2. Only one tab of the site runs a callback for `refresh-token` at a time; the others wait. The lock is released when
   the promise returned by `work` settles (resolves or rejects).
3. `dropped()` never settles, so the lock would never be released, and no tab could renew again. The answer is dropped
   in `renewTokens()`, after the lock.
4. A refused token looks the same whether a thief or another tab of the same browser spent it, so ending the login
   could throw the user out of their other tab. Before this PR the automatic logout only blacklisted an already-spent
   token, which did nothing, so nothing is lost.
5. Test databases are built fresh from the current migrations, and the blacklist app isn't installed anymore, so they
   never had its tables. Only databases migrated by the previous release have them.
6. So that the old code's `migrate`, after a rollback, sees the blacklist's migrations as not applied and builds its
   tables again. Without that, the old code would crash on missing tables.
7. The old code checks only its blacklist, which is empty after a rollback, so it accepts every refresh token the new
   code retired: logged-out logins and every rotated-away token. A new key makes every existing token invalid.
</details>

## Next steps
- Codex review round 2 of PR #46; the assistant merges after it.
- Rebase `t-07-logout-throttle` onto this once merged (both change `logout()` in `app.js`).
- With T-10: the daily delete of ended and expired `LoginSession` rows.
