# 003 · T-01: secret key and settings from the environment

- **Date:** 2026-10-10 · **Phase:** Stage 0, critical security
- **Task:** T-01 (fixes SEC-1, SEC-2, OPS-7 in the [audit](../../scaling/01-audit.md))
- **Branch / commit:** `t-01-settings-from-env`, `68468d0` (originally `09cce5a`, before the rebase)
- **Files:** `root/settings.py`, `accounts/tests.py`, `.env.example` (new), `.env` (local only, not committed)
- **Objective:** no secret in the repo; production-safe settings; `check --deploy` clean.

## What we accomplished
- `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` and the new `CSRF_TRUSTED_ORIGINS` are read from environment variables.
- When `DEBUG` is off, the HTTPS protections switch on: the proxy SSL header, the SSL redirect,
  secure cookies, and HSTS for 1 hour.
- A new random key was generated into your local `.env` only. The old key is burned.
- Added `.env.example` and the first 3 tests in the project.
- Merged the docs branch into `main` (fast-forward) and rebased T-01 onto it.
- **Results:**
  - `manage.py test accounts`: **3 tests OK**.
  - `manage.py check`: clean.
  - `check --deploy` with production env vars: the 7 audit warnings (W004, W008, W009, W012, W016,
    W018, W020) are gone. W005 and W021 remain (HSTS subdomains and preload, deliberately off),
    plus drf-spectacular schema warnings that already existed.
  - Starting without the key raises `KeyError: 'DJANGO_SECRET_KEY'`.
- **Not done:**
  - `check --deploy` in CI (needs T-11).
  - Merging T-01 into `main`.
  - Confirming the rebased branch was pushed.

## Concepts I learned
- **Signing and why a public key means anyone can log in as anyone:** [authentication-and-jwt](../concepts/authentication-and-jwt.md)
- **Env vars, fail-safe defaults, DEBUG, HTTPS settings, HSTS:** [configuration-and-secrets](../concepts/configuration-and-secrets.md)
- **Fast-forward merge, rebase, `--force-with-lease`:** [git-branches-merge-rebase](../concepts/git-branches-merge-rebase.md)

## Important code walkthrough

### `root/settings.py`
```python
def env_list(name):
    return [item.strip() for item in os.environ.get(name, '').split(',') if item.strip()]

SECRET_KEY = os.environ['DJANGO_SECRET_KEY']
DEBUG = os.environ.get('DJANGO_DEBUG') == '1'
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS')
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS')
```
- **The order matters.** `load_dotenv()` runs earlier in the file, so by now `.env` has been copied
  into `os.environ`. Variables already set (for example by a server) win over `.env`.
- **`env_list`** turns `"a.com, b.com,"` into `['a.com', 'b.com']`. It strips spaces and ignores empty parts.
- **`os.environ[...]` vs `.get(...)`** is a deliberate choice per setting: required vs optional.

```python
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SSL_REDIRECT', '1') == '1'
    ...
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '3600'))
```
- **The HTTPS settings only apply in production.** Locally, over plain `http://`, they'd break
  logins: secure cookies are never sent over HTTP.
- **`DJANGO_SSL_REDIRECT` can be turned off** for setups where the proxy already redirects.
- **`SECURE_PROXY_SSL_HEADER` is only safe behind a proxy that sets the header itself.** Otherwise
  a client could send `X-Forwarded-Proto: https` and lie.

### `accounts/tests.py`
```python
def forge(self, key):
    now = timezone.now()
    token = AccessToken()                    # a real SimpleJWT token, for its standard claims
    claims = {**token.payload, 'user_id': '1', 'iat': now, 'exp': now + timedelta(minutes=5)}
    return jwt.encode(claims, key, algorithm='HS256')
```
- **This builds a token exactly like an attacker would**, then asks SimpleJWT to validate it
  (`AccessToken(raw)`). With our key it's accepted; with any other key it raises `TokenError`.
- **Why `SimpleTestCase`:** these tests don't need the database. Django won't create a test database
  for them, so they run in milliseconds.
- **What the tests don't prove:** that the key in a *production* environment is strong. That's what
  `check --deploy` (W009) is for.

## Problems we encountered
- [P-03 · The push was refused by auto mode](../problems-and-solutions.md#p-03--claude-codes-auto-mode-refused-the-remote-change-and-a-push)
- [P-05 · `settings.py` "changed" after switching branches](../problems-and-solutions.md#p-05--settingspy-changed-on-disk-after-switching-branches)
- [P-06 · The local and GitHub branches diverged after the rebase](../problems-and-solutions.md#p-06--after-the-rebase-the-local-and-github-copies-of-the-t-01-branch-diverged)

## Engineering decisions
- [001 · Settings and secrets from environment variables](../decisions/001-settings-from-environment.md)
- **HSTS starts at 1 hour**, and subdomains/preload are left off: wrong HSTS can't be undone quickly,
  because browsers cache it.

## What I should remember
- Anything that signs things (`SECRET_KEY`) is as powerful as every user's password combined.
- Leaked secret → **change it**. Deleting it from history isn't enough.
- **Fail safe:** missing config should crash, or fall back to the *safer* behaviour.
- Test the attack itself (a forged token), not just the happy path.
- `check --deploy` is Django's free production checklist.

## Review questions
1. Explain, step by step, how an attacker with the old `SECRET_KEY` logs in as user 1. Which file in our app accepts their token?
2. Why is `DEBUG = os.environ.get('DJANGO_DEBUG') == '1'` safer than `os.environ.get('DJANGO_DEBUG', 'True') == 'True'`?
3. Debugging scenario: you deploy, set `DJANGO_DEBUG=0`, and every page loops redirecting to `https://`. What's the likely cause, and which setting is involved?
4. Why do the HTTPS settings only apply when `DEBUG` is off?
5. Why does `test_token_signed_with_another_key_is_rejected` matter more than the "accepted" test?
6. After the rebase, why would a normal `git push` of the T-01 branch be rejected?

<details><summary>Answer key</summary>

1. Build a payload `{"token_type": "access", "user_id": "1", "exp": …}`, sign it with HMAC-SHA256 and
   the key, and send it as `Authorization: Bearer …` (checked by `LastSeenJWTAuthentication`) or as
   `?token=` on the WebSocket (`chats/middleware.py`).
2. With `== '1'`, any missing or odd value means production mode. The other version defaults to *on*.
3. The proxy isn't sending `X-Forwarded-Proto: https`. Django thinks every request is HTTP, so
   `SECURE_SSL_REDIRECT` redirects forever. Fix the proxy header; `SECURE_PROXY_SSL_HEADER` is the
   setting that reads it.
4. Locally there's no HTTPS. Secure cookies would never be sent, and the redirect would break the dev server.
5. It reproduces the actual vulnerability. A system that accepts everything also passes the "accepted" test.
6. The remote has `09cce5a`, and the local branch has `68468d0`, which doesn't contain it. Git refuses
   to drop remote commits without `--force-with-lease`.
</details>

## Next steps
- You: push the rebased branch with `--force-with-lease`, then open a PR.
- T-08, then T-11 (tests and CI, including `check --deploy`).
- Review beforehand: [configuration-and-secrets](../concepts/configuration-and-secrets.md).
