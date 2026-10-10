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
- **Fix:** `git remote set-url origin https://github.com/sanjarbek-ashurboyev/OnlineChat.git`. Still **open**: see P-03.
- **Lesson:** redirects are a convenience, not a guarantee. If someone creates a new repository
  at the old name, pushes would go there.

## P-03 · Claude Code's auto mode refused the remote change and a push

- **Sessions:** [002](sessions/002-review-and-first-commit.md), [003](sessions/003-t01-settings-from-environment.md)
- **Observed:** `git remote set-url` was denied ("Remote Repoint"). Later,
  `git commit && git push` was denied ("Out-of-Place Publication").
- **Root cause:** a safety classifier stops the AI from changing where code is published.
  *Hypothesis* for the second denial: the push target was the old, redirected URL from P-02.
- **Fix:** split the work. The local commit ran on its own; you run the remote change and the push yourself.
- **Lesson:** separate local actions (commit) from outward ones (push, changing the remote).
  Outward actions deserve a human check.

## P-04 · `makemigrations --check` warned it couldn't connect to Postgres

- **Session:** [002](sessions/002-review-and-first-commit.md)
- **Observed:** `connection to server at "127.0.0.1", port 5432 failed: FATAL: role "onlinechat_user" does not exist`,
  followed by `No changes detected`.
- **Root cause (Hypothesis):** the audit (OPS-9) found a Homebrew Postgres on `127.0.0.1:5432`
  that answers instead of the Docker one, and it doesn't have our user. We didn't re-verify
  this time.
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
- **Fix:** `git push --force-with-lease origin t-01-settings-from-env`, run by you. Not confirmed yet.
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
