# Authentication and JWT

**Prerequisite:** you know Django's `request.user` and that passwords are stored hashed.

## 1. Simple definition
- **Authentication** answers "who are you?". **Authorization** answers "what are you allowed to do?".
- A **JWT (JSON Web Token)** is a small signed ticket: `header.payload.signature`, each part
  base64-encoded. The payload says who you are and when the ticket expires. The signature proves
  the server issued it.

## 2. Why it exists
After you log in, every later request must prove it's you, without sending your password every time.
- **Sessions** solve this with a random ID in a cookie, looked up in the database on each request.
- **JWTs** put the facts in the token itself and *sign* them, so the server only needs to check the
  signature, not look anything up. That suits APIs and WebSockets, which don't use cookies easily.

## 3. How it works, step by step (HS256, which is what SimpleJWT uses by default)
1. You log in with a phone number and password. The server checks the password hash.
2. The server builds a payload, e.g.
   `{"token_type": "access", "user_id": "7", "exp": 1760100000, "iat": ..., "jti": ...}`.
3. It computes `signature = HMAC-SHA256(secret_key, header + "." + payload)`. HMAC is a keyed
   fingerprint: without the key you can't compute it, and changing one byte of the input changes it completely.
4. It returns `header.payload.signature` to the browser.
5. On each request the server recomputes the HMAC with **its** key and compares. Same value means
   genuine and unmodified. Then it checks `exp` (not expired).

**Important:** the payload is only *encoded*, not *encrypted*. Anyone can read it. Never put secrets in it.

## 4. Small example
```python
import jwt                                    # PyJWT, which SimpleJWT uses
token = jwt.encode({'user_id': '7'}, 'server-secret', algorithm='HS256')
jwt.decode(token, 'server-secret', algorithms=['HS256'])   # works
jwt.decode(token, 'wrong-secret', algorithms=['HS256'])    # raises InvalidSignatureError
```

## 5. In our project
- **SimpleJWT** issues tokens at `POST /api/v1/auth/login/`. There are two:
  - an **access** token (default life 5 min), sent with every request;
  - a **refresh** token (default 1 day), used only to get a new access token at `/auth/token/refresh/`.
- **Refresh tokens work once, and logout ends the login** (T-07, sessions 030 and 036,
  [decisions 014](../decisions/014-refresh-rotation-and-logout.md) and [016](../decisions/016-login-sessions.md)):
  - *A row per login:* `accounts.LoginSession`. Every refresh token of that login carries its id in the claim `sid`,
    and the row stores the id (`jti`) of the one refresh token that may be used next.
  - *Rotation:* every refresh answers with a new refresh token too. One `UPDATE` swaps the row's `refresh_jti` from
    the presented token to the new one, but only if it still is the presented one. Two requests with one token: the
    database lets one win; the other changes 0 rows and gets 401 (P-39). A stolen refresh token stops working as
    soon as the real user refreshes.
  - *Logout:* `POST /auth/logout/ {"refresh": ...}` marks the row ended. Any of the login's tokens will do, even an
    older one a stale tab still holds (P-40).
  - *Only refreshes and logouts read the row.* An access token stays valid until it expires (≤ 5 min), and so does
    a socket opened with it. That's the price of not querying the database per request.
  - Until session 036 this was SimpleJWT's **blacklist** (a table of spent tokens). It let one token be spent twice
    at the same moment, and logout couldn't find a login's other tokens.
  - *In the browser,* one tab never spends the same refresh token twice (`state.renewal` is shared), and picks up
    a token another tab of the same account just saved (`renewTokens()` in `assets/app.js`).
  - *Across tabs,* renewals take turns under a **Web Lock** (`navigator.locks.request('refresh-token', fn)`): a lock
    the browser shares between all tabs of one site. A tab that waited first takes the token the tab before it saved
    (`adoptStoredToken()`), so it never spends one that's already spent (P-43, session 036). The request under the
    lock ends after 10 s (`AbortController`, `postRefresh()`), so a hung request can't hold every tab back (P-46).
  - *Only the "Log out" button ends the login* (`logout()`). When the server refuses a tab's refresh token, the tab
    just forgets its tokens (`signOut()`): another tab may have spent that token a moment ago, and its login must
    live on.
- **REST:** `accounts/authentication.py` `LastSeenJWTAuthentication` checks the `Authorization: Bearer …`
  header, and also updates `last_seen` at most once a minute.
- **WebSocket:** `chats/middleware.py` `user_from_token()` checks `?token=`. A bad token makes the user
  `AnonymousUser`, and the consumer closes with code 4401.
- **An open socket's rights end with its token** (session 020). The middleware passes the token's `exp`
  to the consumer, which closes the socket with 4401 at that moment; the browser renews its token and
  reconnects. A check every 60 s also closes it if the account was disabled
  ([decision 006](../decisions/006-socket-rights-end-with-the-token.md)).
- **The signing key is `SECRET_KEY`**, because SimpleJWT's `SIGNING_KEY` defaults to it. That's why the
  committed key was critical: with it, anyone could sign `{"user_id": "1"}` themselves. See
  [session 003](../sessions/003-t01-settings-from-environment.md).
- **Tests** in `accounts/tests.py` (`SigningKeyTests`) forge tokens with our key (accepted) and with another
  key (rejected).

## 6. Alternatives
| Option | Pros | Cons |
|---|---|---|
| Session cookie | Easy to revoke (delete the row); Django built-in | Needs CSRF protection; awkward for mobile apps and WebSockets |
| **JWT (HS256)** | No lookup per request; works on any transport | An access token can't be revoked before `exp` (SEC-7; refresh tokens can since T-07); a leaked key breaks everything |
| JWT (RS256) | Signed with a private key, verified with a public key, so other services can verify without being able to sign | More setup |
| OAuth / OpenID Connect provider | Delegate login to Google and others | External dependency; overkill here |

## 7. Common mistakes
- **Committing the signing key** (we did; fixed in T-01). Anyone who reads it can be anyone.
- **Thinking JWT payloads are secret.** They're readable by anyone.
- **Long-lived access tokens.** Because JWTs can't be revoked, keep them short and refresh them.
- **Turning on rotation without fixing the client.** With single-use refresh tokens, two requests that refresh at
  the same moment, or two tabs with their own copy, spend the same token twice, and the second one signs the user out.
- **"Single use" checked in two steps on the server.** "Is it spent?" then "mark it spent" lets two requests that
  arrive together both through (P-39). The mark must carry the check (`UPDATE ... WHERE jti = <presented>`).
- **Revoking a token instead of the login.** With rotation a login has many tokens over time; logout has to end all
  of them, whichever one the client still holds (P-40).
- **Ending the login because a refresh was refused.** Once logout ends every tab's login, a tab that merely lost a
  refresh race to its neighbour would sign both out (P-43). Only the user's own "Log out" should end it.
- **A lock callback that never finishes.** A Web Lock is held until the callback's promise settles. Our `dropped()`
  promise never settles, so it must stay *outside* the lock, or one signed-out tab would block every other tab's
  renewals forever. The same goes for a request that never ends: give it a time limit (`AbortController`, P-46).
- **Checking a token only when a long-lived connection opens.** A WebSocket can stay open for hours, so its
  token expires *during* the connection. Until session 020, ours stayed authorized forever.
- **Confusing authentication with authorization.** A valid token proves who you are. You still have to
  check that *this* user may read *this* chat (`get_chat()` filters by `user1`/`user2`).
- **Tokens in URLs** end up in server and proxy logs. We accept this for the WebSocket, with mitigations
  planned (SEC-8).

## 8. When to use it
JWTs fit stateless APIs, mobile clients and WebSockets. For a classic server-rendered Django site,
sessions are simpler and safer by default.
