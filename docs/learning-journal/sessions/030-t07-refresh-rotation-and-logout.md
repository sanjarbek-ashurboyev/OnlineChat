# 030 · T-07: refresh tokens work once, and logout ends them on the server

- **Date:** 2026-10-13 · **Phase:** Stage 0
- **Task:** T-07, refresh rotation and server-side logout ([backlog](../../scaling/03-operations.md), audit SEC-7) ·
  **Branch:** `t-07-refresh-rotation-logout`, stacked on `t-05-chat-by-phone` (PR #39), which is stacked on PR #38
- **Files:** `root/settings.py`, `accounts/views.py`, `accounts/urls.py`, `assets/app.js`, `accounts/tests.py`,
  `chats/test_browser.py`, `root/test_schema.py`, docs
- **Objective:** a copied refresh token stops working once the real user refreshes or logs out.

## What was done
1. **Checked first what existed:** nothing. No `SIMPLE_JWT` settings (library defaults: access 5 min, refresh 1 day,
   no rotation), no blacklist app, and logout only cleared `localStorage`.
2. **Read the library** (SimpleJWT 5.5.1). With the `token_blacklist` app installed, a *refresh* token is looked up
   in the blacklist when it's used; an *access* token is not. So this adds no query to ordinary requests or sockets.
3. **Server tests first** (`RefreshRotationAndLogoutTests`): a refresh returns a new refresh token and the old one is
   refused; after logout the token is refused; logout needs no access token; a bad token or an access token can't log
   out; logging out one device leaves another signed in. On the old code: **4 failures**; the last one is a guard
   (it passed already).
4. **Server code:** `ROTATE_REFRESH_TOKENS` + `BLACKLIST_AFTER_ROTATION`, the `token_blacklist` app, and
   `POST /api/v1/auth/logout/` (`LogoutView`, SimpleJWT's `TokenBlacklistView` with our `refresh` throttle).
   The schema test lists logout as public.
5. **Browser tests first** (`RefreshRotationTests`): two requests that need a new token share one refresh; a renewal
   made by another tab is picked up; another account's token is never picked up; logout retires the token on the
   server. On the old client: **2 failures + 1 error** (two refreshes, a 401, no logout request); the account check
   is a guard.
6. **Client code** (`assets/app.js`): `refreshAccess()` shares one renewal (`state.renewal`); `renewTokens()` retries
   once with the token another tab of the same account saved; `logout()` tells the server, without waiting.
7. **Results:**
   - `make test`: **157 run, OK (15 skipped)**.
   - Real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True`: **192 tests, OK**.
   - `makemigrations --check`: no changes (the blacklist's migrations ship with SimpleJWT). Ruff 0.16.10: clean.
   - Local dev database: `manage.py migrate` applied the `token_blacklist` migrations.

**Not done:**
- Access tokens (and a socket opened with one) still work up to 5 minutes after logout.
- `flushexpiredtokens` isn't scheduled anywhere yet. It belongs to the deploy setup (T-10).
- Two tabs refreshing within the same few milliseconds can still sign one out (see the decision).

## Concepts

### Rotation
- **Simple definition:** every time you use a refresh token, you get a new one, and the old one is retired.
- **Why:** a thief who copies your refresh token has to use it before you do. As soon as either of you refreshes,
  the other one's copy stops working, and a reuse shows up as a refused token.
- **Example:** login gives `R1`. Refresh with `R1` → `A2` + `R2`, and `R1` goes on the blacklist. Refresh with `R1`
  again → 401.

### Blacklist (deny list)
A table of tokens that are refused even though their signature and expiry are fine. A JWT can't be "deleted",
because the server keeps no copy. So to revoke one, you remember its id (`jti`) and check it on use. SimpleJWT checks
it only for refresh tokens: one query per refresh, not one per request.

### Single-flight
"Only one at a time; everyone else waits for the same result." Two API calls that both get a 401 now await the
**same** renewal promise instead of starting two. With single-use tokens, the second refresh would be refused and
sign the user out.

## Walkthrough: `assets/app.js`
```js
function refreshAccess() {
  if (!state.renewal) {
    const renewal = renewTokens().finally(() => {
      if (state.renewal === renewal) state.renewal = null;
    });
    state.renewal = renewal;
  }
  return state.renewal;
}
```
- The first caller starts the renewal; every caller during it gets the same promise.
- `finally` clears it only if it's still *ours*. Logout sets `state.renewal = null`, so a renewal from before logout
  that settles late can't clear the next session's.

```js
  if (res.status === 400 || res.status === 401) {
    if (session !== state.session) return dropped();
    const stored = localStorage.getItem('refresh');
    if (stored && stored !== sent && tokenUser(stored) === tokenUser(sent)) {
      state.refresh = stored;
      return renewTokens();
    }
    return false;
  }
```
- Refused? Maybe another tab spent our token first. Every tab shares `localStorage`, so its new token is there.
- `tokenUser()` reads `user_id` from the token's middle part (a JWT payload is readable by anyone, only the
  signature is secret). If another tab signed in as someone *else*, the ids differ and we don't take it: otherwise
  this tab would quietly become that person (the H-04 kind of bug).
- It retries at most once per new token: the retry sends `stored`, so if that's refused too, `stored === sent`.

```js
  if (state.refresh) {
    fetch(`${API}/auth/logout/`, { method: 'POST', ..., keepalive: true }).catch(() => {});
  }
```
- Not awaited: logout must work instantly, even offline. `keepalive` lets the request finish even if the page closes.

## Problems
None in the code. While planning, two would-be bugs were found by reading `app.js` before turning rotation on
(concurrent 401s, and tabs with their own token copy). Each got a browser test that failed first.

## Decisions
- [Decision 014](../decisions/014-refresh-rotation-and-logout.md): rotation + blacklist, public logout endpoint,
  share renewals in a tab, pick up another tab's token only for the same account.

## What I should remember
- Turning on a server setting can break the client. Read how the client uses the thing before changing its rules.
- A JWT can't be deleted; revoking one means remembering it and checking on use. Check the rare, long-lived token
  (refresh), not the frequent, short-lived one (access).
- Access tokens still live ≤ 5 min after logout. Say that out loud; don't claim "logout is instant".

## Review questions
1. Before T-07, what could someone do with a copy of your refresh token, and for how long?
2. Why does SimpleJWT check the blacklist only for refresh tokens?
3. With rotation on, what goes wrong if two API calls get a 401 at the same time and each refreshes?
4. Why does `renewTokens()` compare `user_id`s before using the token from `localStorage`?
5. Why doesn't `logout()` wait for the server's answer?
6. You log out, but someone who copied your tokens has a socket open elsewhere. How long can it stay open?

<details><summary>Answer key</summary>

1. Make new access tokens, as you, until the refresh token expired: up to a day. Logging out didn't stop it.
2. Checking means a database query. Access tokens are used on every request and socket; refresh tokens about every
   5 minutes. Checking the rare one keeps requests fast, at the price of access tokens living until they expire.
3. Both send the same refresh token. The first one retires it; the second is refused, and the client treats a
   refused refresh as "signed out". Sharing one renewal (`state.renewal`) avoids it.
4. Another tab may have signed in as a different account. Its token would make this tab act as that account while
   still showing the first account's chats.
5. Signing out must work offline and instantly; the answer changes nothing in the page. `keepalive` lets the request
   finish in the background.
6. Until its access token expires (≤ 5 minutes): the consumer closes it with 4401 then (decision 006). It can't
   renew, because the refresh token is on the blacklist. (Your own tab closes its socket at logout.)
</details>

## Next steps
- `/readyz` (T-21 / T-12 step 3).
- T-13 (connection pool), with a load test before and after.
- When deploying (T-10): run `migrate` before the new code serves, and schedule `flushexpiredtokens` daily.
