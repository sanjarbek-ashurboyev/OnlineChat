# 014 · Refresh tokens rotate; logout blacklists; tabs share renewals

- **Date:** 2026-10-13 · **Status:** Accepted (T-07, session 030)

## Problem
Audit SEC-7: a refresh token lived for a day and could be used any number of times. Logging out only deleted it
from the browser. A copy of it (a stolen laptop, malware, a leaked log) kept making access tokens for the rest of
the day, and there was nothing the server could do about it.

## Options considered
1. **Rotation + blacklist** (SimpleJWT's `ROTATE_REFRESH_TOKENS` + `BLACKLIST_AFTER_ROTATION`, plus a logout endpoint
   that blacklists). Each refresh token works once.
2. **Rotation without the blacklist.** New tokens on each refresh, but the old ones keep working until they expire.
   No real gain.
3. **Server-side sessions** (a cookie and a session row) instead of JWTs. Easy to revoke, but a big rewrite of REST,
   the socket's auth and the client.

And for the browser, where two tabs (or two requests) could spend the same single-use token:

- **(a) Share one refresh per tab, and on refusal pick up the token another tab saved, if it's the same account.**
- **(b) A cross-tab lock** (`navigator.locks` or `BroadcastChannel`) so only one tab ever refreshes.
- **(c) Grace period:** the server accepts a just-retired token for a few seconds. SimpleJWT doesn't offer it.

## Chosen: 1 with (a)
- Option 1 is two settings, one installed app and one view: the library already does the work.
- Only refresh tokens are checked against the blacklist, so ordinary requests and sockets cost no extra query.
  The cost is one database write per refresh (each online user about every 5 minutes) and per login.
- (a) is small and local to `refreshAccess()`. Tabs already share `localStorage`, so the token another tab saved is
  right there. The account check (the `user_id` inside the token) stops a tab from becoming someone else after
  the other tab signed in as a different user.
- Logout is public (no access token needed): the access token may have expired, and the refresh token is itself
  the proof. It shares the `refresh` throttle (30/min per IP).

## Disadvantages and limits
- **Access tokens still live up to 5 minutes after logout**, and so does a socket opened with one (it closes at
  the token's expiry, decision 006). Fixing that needs a check per request.
- **Two tabs refreshing in the same few milliseconds** can still sign one out: the refusal can arrive before the
  other tab saved its new token. Rare; the user signs in again.
- **The blacklist grows** by a row per refresh. `manage.py flushexpiredtokens` deletes expired ones; it must be
  scheduled (daily) when we deploy.
- Every running server needs `migrate` for the new tables before this code serves requests.

## When another option is better
- **(b) a cross-tab lock** if users report being signed out with many tabs open.
- **Server-side sessions (3)** if we need instant revocation of *access* (e.g. "sign out everywhere now" for a
  compromised account).
