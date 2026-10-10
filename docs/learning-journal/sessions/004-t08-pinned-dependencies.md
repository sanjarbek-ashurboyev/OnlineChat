# 004 · T-08: complete, pinned dependencies

> **Superseded in part (2026-10-10):** this was the first version of T-08, compiled with Python 3.14 on a
> stale `main`. It was redone on the real `main` and compiled for Python 3.13 (45 pins), with `pip-audit`
> in CI: see [session 006](006-syncing-with-github.md). The concepts here still apply.

- **Date:** 2026-10-10 · **Phase:** Stage 0
- **Task:** T-08 (fixes SEC-10, OPS-3)
- **Branch:** `t-08-pinned-deps`, **not committed yet**
- **Files:** `requirements.in` (new), `requirements.txt` (regenerated), `.github/dependabot.yml` (new)
- **Objective:** a fresh `pip install -r requirements.txt` gives a working app, with every version pinned.

## What we accomplished
- Listed what the code actually imports (`grep` over `accounts`, `chats`, `root`), plus what
  `settings.py` loads by name (`daphne`, `channels_redis`…).
- Wrote `requirements.in` with 12 direct dependencies:
  - **added** `daphne`, `channels`, `channels-redis`, `redis` and `psycopg[binary,pool]`;
  - **dropped** `psycopg2-binary`, `django-filter` and `Markdown`, which nothing imports.
- Compiled `requirements.txt` with `pip-compile --strip-extras` (51 pins). The tool ran in a scratch
  virtualenv, so your `.venv` wasn't touched.
- Added Dependabot: weekly for the app, monthly for `loadtest/`.
- **Results**, in a brand-new virtualenv:
  - all packages import, and `psycopg_any.is_psycopg3` is `True`;
  - `manage.py check` is clean and there are no missing migrations;
  - `from root.asgi import application` works;
  - `pip-audit`: no known vulnerabilities;
  - `manage.py test`: **0 tests** (none on `main`).
- **Not done:**
  - committing;
  - `pip-audit` in CI (T-11);
  - syncing your local `.venv`.

## Concepts I learned
- **Direct vs transitive dependencies, pinning, pip-tools, extras, `~=`:** [dependency-management](../concepts/dependency-management.md)

## Important code walkthrough
```text
Django~=6.1.0
daphne              # ASGI server; listed in INSTALLED_APPS
channels-redis      # CHANNEL_LAYERS backend
redis               # Django cache backend and chats/presence.py
psycopg[binary,pool]
django-phonenumber-field[phonenumberslite]
pillow              # User.avatar ImageField
```
- **Why these were missing before:** none of them is imported in the usual `import x` way in our
  code. Django loads them **by name from strings** in `settings.py` (`'daphne'` in `INSTALLED_APPS`,
  `'channels_redis.core.RedisChannelLayer'`). A plain search for imports misses them, so check
  settings strings too.
- **`django-phonenumber-field[phonenumberslite]`:** the field needs a phone number library. The
  `lite` variant skips geocoding data we don't use.
- **The `# via` lines** in `requirements.txt`, e.g. `twisted … # via daphne`, answer "why is this
  here?". Before deleting a package from `requirements.in`, check what it pulls in.

## Problems we encountered
- [P-07 · Development and a fresh install used different Postgres drivers](../problems-and-solutions.md#p-07--development-and-a-fresh-install-would-use-different-postgres-drivers)

## Engineering decisions
- [002 · Pin with pip-tools](../decisions/002-pinned-dependencies-with-pip-tools.md)
- **Removing unused packages** instead of keeping them "just in case": less to update, smaller attack surface.

## What I should remember
- Verify an install in a **fresh** environment; your daily one lies.
- Django loads many dependencies by string from settings, so search there too.
- Pinned isn't the same as safe: keep updating (Dependabot) and scanning (`pip-audit`).

## Review questions
1. Where in this project are dependencies referenced by **string** rather than `import`? Name two.
2. You add `celery` to `requirements.in` but forget to run `pip-compile`. What happens on the server?
3. Why was `psycopg[pool]` added now, even though nothing uses pooling yet?
4. Debugging scenario: production logs `ModuleNotFoundError: No module named 'channels_redis'`, but it works on your laptop. What happened, and how would the fresh-venv check have caught it?

<details><summary>Answer key</summary>

1. Any two of: `INSTALLED_APPS` (`'daphne'`, `'channels'`, `'rest_framework'`…),
   `CHANNEL_LAYERS['default']['BACKEND']` (`channels_redis`), the `CACHES` backend (needs `redis`),
   `DEFAULT_SCHEMA_CLASS` (`drf_spectacular`), `DEFAULT_PAGINATION_CLASS` (`rest_framework`).
2. Nothing new is installed, because the server installs from `requirements.txt`. Celery imports fail.
3. Decision 1.2 in the plan uses it for PERF-2. Adding it with the driver keeps the two versions in sync,
   and the cost is one small package.
4. The package was installed by hand locally and never listed. A fresh venv built from the file would
   have failed on the import.
</details>

## Next steps
- Commit `requirements.in`, `requirements.txt` and `.github/dependabot.yml` on this branch.
- Sync `.venv`: `pip install -r requirements.txt`, then uninstall `psycopg2-binary`, `django-filter` and `Markdown`.
- T-11: tests and CI, with `pip-audit` in it.
