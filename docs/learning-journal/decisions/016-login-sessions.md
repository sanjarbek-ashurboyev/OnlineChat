# 016 · A row per login: single-use refresh tokens and logout by session

- **Date:** 2026-10-13 · **Status:** Accepted (Codex review of #38–#43, session 036). Replaces the "rotation +
  blacklist" part of [decision 014](014-refresh-rotation-and-logout.md); the browser side of 014 is unchanged.

## Problem
With SimpleJWT's blacklist (decision 014):
1. Two requests with the same refresh token at the same moment both got new tokens (P-39): a thief who sends the
   stolen token at the same time as the real tab keeps a working login.
2. Logout ended only the token it was given. A tab holding an older token of the same login got 401, and the login
   went on in the other tab (P-40).

## Options considered
1. **Keep the blacklist, check `created`**: in `get_or_create`, `created=False` means someone else spent it → 401.
   Fixes 1 only; logout still can't find the other tokens of a login.
2. **Blacklist + a session row** (`sid`) for logout, locking the row (`SELECT ... FOR UPDATE`) during a refresh.
   Fixes both, but keeps two mechanisms: the blacklist (two `INSERT`s per refresh) and the session.
3. **A session row only.** The row stores the id (`jti`) of the one usable refresh token. Refresh =
   `UPDATE ... SET refresh_jti = new WHERE id = sid AND refresh_jti = presented AND ended_at IS NULL`; logout =
   set `ended_at`. Remove the blacklist app.
4. **Server-side sessions instead of JWTs** (decision 014's option 3). Also instant revocation of access, but a
   rewrite of REST auth, the socket's auth and the client.

## Chosen: 3
- One mechanism for both problems. The database itself decides which of two requests wins, in one statement.
- Cheaper than before: one `UPDATE` per refresh instead of two `INSERT`s; one `INSERT` per login.
- Small: one model, three serializers, no change in the browser or for the socket.

## Disadvantages and limits
- **Everyone signed in before the deploy signs in once more**: their tokens have no `sid`.
- **No pruning yet**: ended and expired rows stay until a job deletes them (one row per login, so slow growth; with T-10).
- **Access tokens still work up to 5 minutes after logout**, like before. The `sid` is in access tokens too, so a
  per-request check would be possible later, at one query per request.
- **An old stolen refresh token can end the login** (sign the user out). It can't renew it.
- ~~The old `token_blacklist_*` tables stay in databases that had them; drop them by hand.~~ Wrong: their rows
  made deleting a user fail. Migration `accounts.0004` drops them (P-42).
- **Rolling back to the blacklist code needs a new `DJANGO_SECRET_KEY`**: the old code would accept every token this
  one retired. Steps in `docs/scaling/03-operations.md` (T-07).

## Update (Codex review of #46): who may end a login
A tab that lost a refresh race to another tab (P-43) signed out with `logout()`, which ends the login on the server,
so the winner's new token died too. Options:
1. **Revoke whenever a refresh is refused** (as before). A refused token *could* mean a thief spent it first, and
   revoking would throw the thief out. But a refused token looks the same when another tab of the same browser spent
   it, and then it throws out the user. We can't tell the two apart.
2. **Only the "Log out" button ends the login on the server; a refused refresh only signs that tab out.**

**Chosen: 2**, plus a cross-tab lock (`navigator.locks`) so the same browser's tabs don't race at all. Before this
PR a refused token's automatic logout blacklisted a token that was already spent, which did nothing, so 2 gives up
nothing we had. Theft detection ("a spent token came back: end the login") would need the server to tell *which*
token came back, and is not planned.

## When another option is better
- **4** if we need "sign out everywhere *now*", access tokens included (a compromised account).
- **A per-request `sid` check** (still option 3) if 5 minutes after logout becomes too long.
