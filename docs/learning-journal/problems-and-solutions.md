# Problems and solutions

Real problems from this project: what we saw, why it happened, how we found out, and how
it was fixed. Labels: **Confirmed** = root cause proven; **Hypothesis** = likely but not proven.

---

## P-01 · `__pycache__/` folders were about to be committed

- **Session:** [002](sessions/002-review-and-first-commit.md)
- **Observed:** `git status` listed `accounts/__pycache__/`, `chats/__pycache__/` and others as untracked.
- **Expected:** only source files show up.
- **Root cause (Confirmed):** `.gitignore` didn't list `__pycache__/`. Python writes compiled
  bytecode (`.pyc`) there whenever it imports a module.
- **How we found it:** reading `git status` *before* `git add`, not after.
- **Fix:** added `__pycache__/` and `*.pyc` to `.gitignore`.
- **Lesson:** always read `git status` before staging, and stage explicit paths
  (`git add docs loadtest`) instead of `git add .`.

## P-02 · The GitHub repository had moved

- **Session:** [002](sessions/002-review-and-first-commit.md)
- **Observed:** the push succeeded, but GitHub printed `This repository moved. Please use the new location: https://github.com/sanjarbek-ashurboyev/OnlineChat.git`.
- **Root cause (Confirmed):** the repository was renamed or transferred. GitHub redirects the old
  URL, but the local remote `origin` still pointed at `uzbillionaire/OnlineChat`.
- **Fix:** `git remote set-url origin https://github.com/sanjarbek-ashurboyev/OnlineChat.git`. **Resolved** 2026-10-10 (session 006).
- **Lesson:** redirects are a convenience, not a guarantee. If someone creates a new repository
  at the old name, pushes would go there.

## P-03 · Claude Code's auto mode refused the remote change and a push

- **Sessions:** [002](sessions/002-review-and-first-commit.md), [003](sessions/003-t01-settings-from-environment.md)
- **Observed:** `git remote set-url` was denied ("Remote Repoint"). Later,
  `git commit && git push` was denied ("Out-of-Place Publication").
- **Root cause:** a safety classifier stops the AI from changing where code is published.
  *Hypothesis* for the second denial: the push target was the old, redirected URL from P-02.
- **Fix:** split the work, so the local commit ran on its own. Later you added the allow rules
  `Bash(git push:*)` and `Bash(git remote set-url:*)` to `.claude/settings.local.json` yourself. The AI
  isn't allowed to add rules to its own permissions ("Self-Modification"), which is correct. **Resolved.**
- **Lesson:** separate local actions (commit) from outward ones (push, changing the remote).
  Outward actions deserve a human check.

## P-04 · `makemigrations --check` warned it couldn't connect to Postgres

- **Session:** [002](sessions/002-review-and-first-commit.md)
- **Observed:** `connection to server at "127.0.0.1", port 5432 failed: FATAL: role "onlinechat_user" does not exist`,
  followed by `No changes detected`.
- **Root cause (Confirmed in session 007):** `lsof -iTCP:5432 -sTCP:LISTEN` shows a `postgres` process
  run from `/opt/homebrew/opt/postgresql@14`. A Homebrew **Postgres 14** answers on `127.0.0.1:5432`
  instead of the Docker one, and it doesn't have our user. It's also older than Django 6.1 supports (15+).
- **Why the check still worked:** `makemigrations` only *warns* when it can't reach the database
  to check migration history. Comparing models to migration files doesn't need the database.
- **To confirm:** `lsof -iTCP:5432 -sTCP:LISTEN` shows which program owns the port.
  The planned fix is in T-10.
- **Lesson:** a warning in the output doesn't always mean the result is invalid. Read what the
  command actually needed.

## P-05 · `settings.py` "changed on disk" after switching branches

- **Session:** [003](sessions/003-t01-settings-from-environment.md)
- **Observed:** after `git checkout main`, `root/settings.py` showed the old hard-coded key again.
- **Root cause (Confirmed):** expected behaviour. A checkout replaces tracked files with that
  branch's version. T-01 lived only on its branch.
- **Lesson:** a branch is a whole version of the project. If a fix "disappears", check which
  branch you're on (`git branch --show-current`).

## P-06 · After the rebase, the local and GitHub copies of the T-01 branch diverged

- **Session:** [003](sessions/003-t01-settings-from-environment.md)
- **Observed:** `origin/t-01-settings-from-env` pointed at `09cce5a`, the local branch at `68468d0`.
- **Root cause (Confirmed):** the branch had been pushed before the rebase, and a rebase creates new commits.
- **Fix:** you pushed the rebased branch yourself. In session 006 the branch was rebuilt again and pushed
  with `--force-with-lease=t-01-settings-from-env:68468d0`. That only overwrites if GitHub still has `68468d0`. **Resolved.**
- **Lesson:** rebase before you push, or accept a force push. Only use `--force-with-lease`, never plain `--force`.

## P-07 · Development and a fresh install would use different Postgres drivers

- **Session:** [004](sessions/004-t08-pinned-dependencies.md)
- **Observed:** `requirements.txt` listed `psycopg2-binary`, but `pip list` in `.venv` showed `psycopg` 3.3.5 as well.
- **Root cause (Confirmed):** Django uses psycopg 3 when both are installed. So your machine ran
  psycopg 3, while a server installing from the file would get psycopg2.
- **Fix:** `requirements.in` asks for `psycopg[binary,pool]`, and psycopg2 is gone. Proven in a fresh venv:
  `psycopg_any.is_psycopg3 == True`.
- **Lesson:** the environment you test in must be built from the same file as production.

## P-08 · The server fails between 100 and 200 users online

- **Session:** [001](sessions/001-project-analysis-and-load-test.md)
- **Observed:** with a heavy profile, 100 users were healthy and 200 failed (message p95 1,538 ms).
- **Root cause (model consistent with the measurement, not yet proven):**
  1. All database calls from WebSocket consumers share **one thread** per process (PERF-1).
  2. Each call opens a new Postgres connection: 6.2 ms to connect versus 0.22 ms per query (PERF-2).
  3. One message costs about 7 calls (PERF-3).

  Together that's about 86% thread utilisation at 200 users, and queues explode past roughly 70%.
- **How we found it:** a step load test, measuring connect versus query time, reading the
  library source (`asgiref`, `channels/db.py`), and arithmetic. See the
  [performance guide](concepts/performance-and-load-testing.md).
- **Fix:** planned for Stage 1: connection pooling, fewer writes per message, then more processes.
  T-12 will confirm the cause with a profiler.
- **Lesson:** measure first. The cheap fix (reusing connections) beats the expensive one
  (rewriting in FastAPI).

## P-09 · Local `main` was five commits behind GitHub

- **Session:** [006](sessions/006-syncing-with-github.md)
- **Observed:** before the first push of `main`, `git fetch` showed `main [origin/main: ahead 2, behind 5]`.
  GitHub had commits from 2026-10-06 to 10-08 (PR #5) that the local copy never pulled: secrets from env,
  dependencies, 48 tests, CI, the message length cap, and the avatars removed from git.
- **Expected:** the local `main` matches GitHub before any work starts.
- **Root cause (Confirmed):** the local clone was never updated after that work landed on GitHub.
  `origin` also pointed at the old repository address, so nothing showed the difference. Every git
  command we ran (`status`, `log`) only looks at local data until you `fetch`.
- **Consequences:** the audit, T-01 and T-08 were built on stale code. Part of T-01 and T-08, and most
  of T-11, were already done.
- **How we found it:** `git fetch`, then `git branch -vv`, which shows ahead/behind counts, then
  `git diff --stat` between the two versions.
- **What didn't work:** pushing would have been rejected (non-fast-forward). A forced push would have
  **deleted PR #5's work** from GitHub. Neither was tried.
- **Fix:**
  1. Rebased our docs and journal commits onto `origin/main`. Only `.gitignore` conflicted; both versions were combined.
  2. Rebuilt T-01 and T-08 as small additions on top of the existing work, instead of replacing it.
  3. Added a status update to the audit.
- **Verified:** 48 tests and Ruff pass on the new `main`, `main` pushed as a normal fast-forward,
  and both branches pushed after their tests passed.
- **Lesson:** run `git fetch` (or `git pull`) **before** you start, and read `ahead/behind` in
  `git status -sb`. An audit is only as current as the commit it was run on, so write that commit down,
  as `01-audit.md` did. That's how we could tell exactly what had changed.

## P-10 · 39 tests failed after adding the HTTPS settings

- **Session:** [006](sessions/006-syncing-with-github.md)
- **Observed:** after adding the `if not DEBUG:` block to `settings.py`, `make test` gave `FAILED (failures=29, errors=10)`.
- **Expected:** all 48 pass. We predicted this failure *before* running the tests.
- **Root cause (Confirmed):** `root/settings_test.py` imports the main settings with `DJANGO_DEBUG` unset,
  so DEBUG is off and `SECURE_SSL_REDIRECT = True`. Django's test client sends plain HTTP, so every
  request got a **301 redirect** to `https://` instead of the real response.
- **Fix:** `SECURE_SSL_REDIRECT = False` in `root/settings_test.py`, with a comment explaining why.
  The other production settings (secure cookies, HSTS) stay on in tests, so tests run close to production.
- **Verified:** 48/48 tests pass, plus the 2 new ones.
- **Lesson:** when you change settings, think about *every* settings file that imports them. Test settings
  usually inherit production behaviour. That's good, until something like a redirect breaks the test client.

## P-11 · gitleaks' built-in rules missed our real leaked key

- **Session:** [007](sessions/007-t11-tests-and-ci.md)
- **Observed:** `gitleaks git .` over the full history: "no leaks found". But commit `3bd73a8` contains the
  original `SECRET_KEY` (confirmed with `git log -S`).
- **Root cause (Confirmed):** gitleaks matches known token formats (AWS keys, GitHub tokens, JWTs…) and generic
  patterns. A Django key like `django-insecure-…` assigned to `SECRET_KEY` matched none of them.
- **Fix:** a custom rule in `.gitleaks.toml` (`django-secret-key`) for hard-coded `SECRET_KEY = '…'` values.
  It found 3 matches:
  - the burned key → listed in `.gitleaksignore` by fingerprint (commit:file:rule:line);
  - the dev-only fallback, in code and in this journal → allowlisted by exact value.
- **Verified:** the repository scan is clean. A scratch repo with a new hard-coded key is caught ("leaks found: 1").
- **Lesson:** a scanner reporting "clean" only means "nothing matched my rules". Test your tools on a known
  positive before trusting a negative.

## P-12 · WebSocket tests passed on SQLite but failed on Postgres

- **Session:** [007](sessions/007-t11-tests-and-ci.md)
- **Observed:** in the new CI job against real Postgres, all 13 tests in `chats/test_consumers.py` errored with
  `psycopg.OperationalError: the connection is closed`. All 40 REST tests passed. On SQLite everything passed.
- **Root cause (Confirmed by reading the library source):**
  1. Django's `TestCase` runs each test inside a transaction, so autocommit is **off**.
  2. Channels' `database_sync_to_async` calls `close_old_connections()` before and after each call (`channels/db.py`).
  3. That calls `close_if_unusable_or_obsolete()`, which **closes** a connection whose autocommit differs
     from the setting (`django/db/backends/base/base.py`). The test's own connection, and its transaction, are gone.
  4. SQLite's `close()` does nothing for an in-memory database, because closing would delete it. That hid the problem.
- **Fix:** `InboxSocketTestCase` now inherits from `TransactionTestCase`. Data is really committed, and the
  tables are emptied after each test. This is what the Channels docs recommend for consumers that use the database.
- **Verified:** 53/53 locally on SQLite, and all four CI jobs pass, including Postgres + Redis.
- **Not a production bug:** production runs with autocommit on. It's purely a test-harness problem.
- **Lesson:** a test database that behaves differently from production can hide bugs, or hide broken tests.
  That's exactly why the Postgres/Redis job was added, and it paid off on its first run.

## P-13 · A burst of disconnects left users "online" (COR-2)

- **Session:** [008](sessions/008-t02-disconnect-marks-offline.md)
- **Observed (load test, session 001):** when 200 clients disconnected together, 97 `disconnect()` calls raised
  `redis.exceptions.MaxConnectionsError` at `group_discard`. The next lines, `mark_offline` and `touch_last_seen`,
  never ran. Those users showed "online" for up to 90 s, and their dead channels stayed in the Redis group for
  up to 24 h, receiving copies of every message.
- **Expected:** closing a socket always marks the user offline, whatever else fails.
- **Root cause, part 1 (Confirmed, code):** `disconnect()` ran the steps in sequence with no error handling,
  so one failing step skipped the rest.
- **Root cause, part 2 (Confirmed by reading the library source):**
  - channels-redis keeps **one connection pool per event loop**, so one per process, shared by all sockets
    (`RedisChannelLayer.connection()` → `RedisLoopLayer`).
  - The pool is redis-py's `ConnectionPool`. It defaults to `max_connections=100`, and when all are in use
    `get_available_connection()` **raises at once** instead of waiting. `BlockingConnectionPool` would wait,
    but channels-redis doesn't use it.
  - 200 simultaneous `group_discard` calls need about 200 connections, so everything past 100 failed. The
    Redis *server* limit (`maxclients`, default 10,000) was never the problem.
- **Fix:**
  - `disconnect()` catches and logs a `group_discard` failure, then still marks the user offline.
  - The stale group entry is harmless and expires by itself (`group_expiry`).
  - Pool sizing is **not changed yet**: it's a capacity decision for Stage 1, to be measured with the load test.
- **Verified:**
  - A test (`test_a_failed_group_discard_still_marks_the_user_offline`) made `group_discard` raise
    `MaxConnectionsError`. It failed before the fix and passes after.
  - 54/54 tests pass.
  - **Not verified yet:** the acceptance check "no presence leftovers after the load test's end-of-run
    disconnects". That needs the local stack running (Docker), and is planned with the baseline load test.
- **Lesson:** cleanup code must not depend on every step succeeding. Do the most important step (mark offline)
  regardless, and log the rest. A "too many connections" error is often a *client-side pool* limit, not the server's.

