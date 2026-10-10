# Configuration and secrets

**Prerequisite:** [Authentication and JWT](authentication-and-jwt.md), for why `SECRET_KEY` matters.

## 1. Simple definition
- **Configuration** is everything that changes between environments (your laptop, a test server,
  production): database addresses, debug mode, domain names.
- **Secrets** are configuration values that give power if leaked: keys, passwords, API tokens.
- **Environment variables** are named values handed to a program by whatever starts it.
  Python reads them with `os.environ`.

## 2. Why it exists
The same code should run everywhere with different settings, and secrets must never be in the
code, because code gets copied, shared and published. This is one of the
"[Twelve-Factor App](https://12factor.net/config)" rules: *store config in the environment*.

## 3. How it works, step by step
1. Locally, `.env` holds lines like `DJANGO_DEBUG=1`. It's listed in `.gitignore`, so it's never committed.
2. `load_dotenv(BASE_DIR / '.env')` at the top of `settings.py` copies those lines into `os.environ`.
   It doesn't overwrite variables that already exist.
3. Settings read `os.environ[...]`. On a server, the hosting platform or a systemd unit sets the real
   values. There's no `.env` file there, or one with locked-down permissions.
4. `.env.example` is committed. It lists every variable name with empty or safe values, so a newcomer
   knows what to set.

## 4. Small example
```python
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']    # required: crash if missing
DEBUG = os.environ.get('DJANGO_DEBUG') == '1'   # optional: off unless exactly "1"
```
`os.environ['X']` raises `KeyError` if the variable is missing. `os.environ.get('X')` returns `None`.
Choose deliberately which one each setting should use.

## 5. In our project (T-01, `root/settings.py`)
- `SECRET_KEY` is required, with no default. A missing key stops startup with `KeyError: 'DJANGO_SECRET_KEY'`.
- `DEBUG` is `True` only when `DJANGO_DEBUG == '1'`. This is **fail safe**: a typo means production mode.
- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are comma-separated lists, read by `env_list()`.
- When `DEBUG` is off:
  - `SECURE_PROXY_SSL_HEADER`: HTTPS ends at the reverse proxy, which tells Django through `X-Forwarded-Proto: https`.
  - `SECURE_SSL_REDIRECT`: `http://` is redirected to `https://`.
  - `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE`: cookies are only sent over HTTPS.
  - `SECURE_HSTS_SECONDS = 3600`: browsers will refuse plain HTTP for this site for 1 hour. It starts
    short because browsers *remember* it; a year-long value plus a broken certificate locks users out.
- **Why DEBUG must be off in production:** error pages show code, local variables and settings to the
  visitor, and Django keeps every SQL query in memory, which looks like a memory leak under load.
- **`manage.py check --deploy`** lists production-unsafe settings. Run it with production env vars.

## 6. Alternatives
| Option | Notes |
|---|---|
| Hard-coded settings | What we had. Unsafe for secrets; needs code edits per environment. |
| **Env vars + python-dotenv** | Chosen; see [decision 001](../decisions/001-settings-from-environment.md). |
| `django-environ` | Same idea, with type parsing (`env.bool`, `env.list`, `env.db_url`). One more dependency. |
| Split settings modules (`settings/dev.py`, `prod.py`) | Clear differences, but secrets still need env vars. Files drift apart. |
| Secrets manager (AWS Secrets Manager, Vault, Doppler) | Rotation and auditing. Worth it with many services or people. |

## 7. Common mistakes
- **A default for the secret key**, e.g. `os.environ.get('KEY', 'dev-key')`. Production silently runs
  with the public default.
- **`DEBUG = os.environ.get('DEBUG', True)`.** Any non-empty string, even `"False"`, is truthy.
- **Deleting a leaked secret from git history and calling it fixed.** Clones and forks keep it.
  **Change it** (generate a new one) instead.
- **Committing `.env`.** Check `.gitignore` before the first commit.
- **Long HSTS before HTTPS is proven.**

## 8. When to use it
Always, for anything that differs between environments or is secret. Constants that are the same
everywhere (`TIME_ZONE`, `PAGE_SIZE`) can stay in code.
