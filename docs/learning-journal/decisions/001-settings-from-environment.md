# 001 · Settings and secrets come from environment variables

- **Date:** 2026-10-10 · **Task:** T-01 · **Status:** Accepted · **Commit:** `763c9da` on `main`, plus `9d3ef86` on branch `t-01-settings-from-env`

> **Update 2026-10-10:** GitHub's `main` already had its own version of this (`763c9da`). It uses
> `DJANGO_DEBUG=True/False` and a dev-only fallback key when DEBUG is on. We kept that version and
> added only the missing parts (HTTPS settings, `CSRF_TRUSTED_ORIGINS`, tests, the CI check) on
> branch `t-01-settings-from-env` (`9d3ef86`). The reasoning below still holds; the code examples in
> session 003 show the first version. See [session 006](../sessions/006-syncing-with-github.md).

## Problem
(The plan's version of this decision: [Decision 0.1 in 02-plan.md](../../scaling/02-plan.md).)

`SECRET_KEY`, `DEBUG = True` and `ALLOWED_HOSTS = []` were hard-coded in `root/settings.py`, in a
public repository. The key signs login tokens, so anyone could forge a login
(see [JWT](../concepts/authentication-and-jwt.md)). The app couldn't be deployed safely without editing code.

## Options considered
1. **Environment variables, loaded from `.env` by python-dotenv** (already installed and already used
   for the database settings).
2. **`django-environ`**: typed helpers (`env.bool`, `env.list`). One more dependency.
3. **Split settings modules** (`settings/base.py`, `dev.py`, `prod.py`). Still needs env vars for
   secrets, and the files drift.
4. **A secrets manager** (Vault, AWS Secrets Manager). Rotation and auditing, but there's no
   production infrastructure yet.

## Chosen: option 1
- No new dependency; same pattern the database settings already use.
- Small and readable: one helper, `env_list()`.
- **Fail-safe defaults:** the key is required (crash if missing), `DEBUG` is on only for exactly `'1'`,
  and the HTTPS protections switch on whenever `DEBUG` is off.

## Disadvantages and limits
- Values are strings. Parsing is by hand (`== '1'`, `int(...)`), so it's easy to get subtly wrong
  in new settings.
- No validation that, e.g., `DJANGO_ALLOWED_HOSTS` is set in production. Django only errors on the first request.
- Anyone with shell access to the server can read the environment.

## When another option is better
- Many settings with types: `django-environ` or `pydantic-settings`.
- Several services, people, or compliance needs: a secrets manager, with rotation.

## Consequences
- Rotating the key logged everyone out. The old key stays public in git history forever and must never be reused.
- Every environment must set `DJANGO_SECRET_KEY`. `.env.example` lists all variables.
