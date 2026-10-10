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
- **REST:** `accounts/authentication.py` `LastSeenJWTAuthentication` checks the `Authorization: Bearer …`
  header, and also updates `last_seen` at most once a minute.
- **WebSocket:** `chats/middleware.py` `user_from_token()` checks `?token=`. A bad token makes the user
  `AnonymousUser`, and the consumer closes with code 4401.
- **The signing key is `SECRET_KEY`**, because SimpleJWT's `SIGNING_KEY` defaults to it. That's why the
  committed key was critical: with it, anyone could sign `{"user_id": "1"}` themselves. See
  [session 003](../sessions/003-t01-settings-from-environment.md).
- **Tests** in `accounts/tests.py` (T-01 branch) forge tokens with our key (accepted) and with another
  key (rejected).

## 6. Alternatives
| Option | Pros | Cons |
|---|---|---|
| Session cookie | Easy to revoke (delete the row); Django built-in | Needs CSRF protection; awkward for mobile apps and WebSockets |
| **JWT (HS256)** | No lookup per request; works on any transport | Can't be revoked before `exp` (SEC-7); a leaked key breaks everything |
| JWT (RS256) | Signed with a private key, verified with a public key, so other services can verify without being able to sign | More setup |
| OAuth / OpenID Connect provider | Delegate login to Google and others | External dependency; overkill here |

## 7. Common mistakes
- **Committing the signing key** (we did; fixed in T-01). Anyone who reads it can be anyone.
- **Thinking JWT payloads are secret.** They're readable by anyone.
- **Long-lived access tokens.** Because JWTs can't be revoked, keep them short and refresh them.
- **Confusing authentication with authorization.** A valid token proves who you are. You still have to
  check that *this* user may read *this* chat (`get_chat()` filters by `user1`/`user2`).
- **Tokens in URLs** end up in server and proxy logs. We accept this for the WebSocket, with mitigations
  planned (SEC-8).

## 8. When to use it
JWTs fit stateless APIs, mobile clients and WebSockets. For a classic server-rendered Django site,
sessions are simpler and safer by default.
