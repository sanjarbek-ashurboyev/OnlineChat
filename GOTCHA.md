# Gotchas

Traps this project has already fallen into. **Read this before starting work.** Each line is a rule;
the link is the full story (what happened, how we found it, the root cause).

Add a line whenever a new mistake costs time. Keep each rule to one or two lines.

## Git and GitHub

- **`git fetch` before you start anything**, then `git status -sb`. "Working tree clean" says nothing
  about GitHub. Our `main` was 5 commits behind for a whole day. → [P-09](docs/learning-journal/problems-and-solutions.md#p-09--local-main-was-five-commits-behind-github)
- **Never answer a rejected push with a forced push.** Find out what's on the remote first. If you rebased
  your *own* branch, use `--force-with-lease`, never plain `--force`. → [P-06](docs/learning-journal/problems-and-solutions.md#p-06--after-the-rebase-the-local-and-github-copies-of-the-t-01-branch-diverged)
- **Stage explicit paths and read `git status` first.** `git add .` picks up `__pycache__`, `.env` and token files. → [P-01](docs/learning-journal/problems-and-solutions.md#p-01--__pycache__-folders-were-about-to-be-committed)
- **A fix "disappeared"? Check which branch you're on.** Switching branches swaps the files. → [P-05](docs/learning-journal/problems-and-solutions.md#p-05--settingspy-changed-on-disk-after-switching-branches)
- **Everything goes through a PR.** `protect-main` blocks direct pushes, requires `lint`, `test`,
  `test-postgres-redis` and `secrets`, and requires the branch to be up to date. → [decision 003](docs/learning-journal/decisions/003-one-branch-per-task.md)
- **Merge PRs one at a time.** After each merge the others are "behind": update them and let CI rerun.
  Two PRs that each pass alone haven't been tested *together* (PRs #6/#7).
- **A required check that's new in `main` never runs on an old PR.** Update the PR's branch so it does.
- **"No checks reported" right after an update usually means "still running".** `test-postgres-redis` takes about 1.5 min.
- **With auto-merge on, check the PR is still open before pushing to it** (`gh pr view N --json state`).
  A commit pushed after the merge sits on a dead branch, and its green checks mean nothing. → [P-15](docs/learning-journal/problems-and-solutions.md#p-15--a-commit-pushed-to-a-pr-after-auto-merge-never-reached-main)
- **When PRs depend on each other, stack them** (branch from the earlier PR's branch) instead of
  duplicating changes. Merge them in order.

## Dependabot

- **Before removing an entry from `dependabot.yml`, close the PRs it created.** Otherwise they're
  orphaned and can never be rebased. → [P-14](docs/learning-journal/problems-and-solutions.md#p-14--dependabot-prs-that-could-never-be-merged)
- **Closing a Dependabot PR skips that release and deletes its branch.** `@dependabot reopen` may not bring it back.
  Of two duplicates, keep the one from the config entry that stays.
- **The `/` entry already covers subfolders** (`loadtest/`). A second entry for a subfolder creates duplicate PRs.
- **Use `@dependabot rebase` to fix a conflict, not GitHub's conflict editor.** Once you add a commit, Dependabot
  stops managing the PR. `@dependabot recreate` is the stronger version.

## Django settings

- **`root/settings_test.py` inherits every production setting** (`DEBUG` is off there). New production-only
  settings can break the test client; e.g. `SECURE_SSL_REDIRECT` turned every request into a 301. → [P-10](docs/learning-journal/problems-and-solutions.md#p-10--39-tests-failed-after-adding-the-https-settings)
- **`DJANGO_DEBUG` is `True`/`False`, not `1`/`0`.** Anything else means production mode, including locally.
- **The dev fallback `SECRET_KEY` exists only when `DEBUG` is on.** Never add a fallback that also applies in production.
- **Django loads many dependencies by *string* in `settings.py`** (`INSTALLED_APPS`, `CHANNEL_LAYERS`, `CACHES`).
  Searching for `import` misses them.

## Tests

- **Tests whose consumers touch the database must use `TransactionTestCase`.** With `TestCase`, Channels closes
  the test's connection on Postgres. SQLite hides it. → [P-12](docs/learning-journal/problems-and-solutions.md#p-12--websocket-tests-passed-on-sqlite-but-failed-on-postgres)
- **Green on SQLite is not green on Postgres.** The `test-postgres-redis` CI job is the real check.
- **"0 tests ran" is not "tests pass".**
- **Write the failing test first, and watch it fail.** When mocking, also assert the mock was called
  (`assert_awaited_once()`); otherwise the test can pass without testing anything.

## Dependencies

- **`pip-compile` keeps existing pins.** Use `--upgrade` or `--upgrade-package NAME` to move on. Don't
  explain a version change before checking this. → [session 006](docs/learning-journal/sessions/006-syncing-with-github.md)
- **Compile with Python 3.13, the version CI uses.**
- **Prove an install in a fresh virtualenv.** Your daily `.venv` hides missing packages. → [P-07](docs/learning-journal/problems-and-solutions.md#p-07--development-and-a-fresh-install-would-use-different-postgres-drivers)
- **Edit `requirements.in`, never `requirements.txt`.**

## Security

- **A leaked secret must be rotated.** Deleting it from git history doesn't help: clones keep it.
- **"No leaks found" only means "nothing matched".** gitleaks' built-in rules missed our real Django key.
  Test a scanner on a planted secret before trusting it. → [P-11](docs/learning-journal/problems-and-solutions.md#p-11--gitleaks-built-in-rules-missed-our-real-leaked-key)
- **`loadtest/tokens.json` holds live login tokens.** It's gitignored; keep it that way.

## Runtime and infrastructure

- **Cleanup code must not depend on every step succeeding.** A failing `group_discard` used to skip "mark
  offline". Log the failure, then do the important step anyway. → [P-13](docs/learning-journal/problems-and-solutions.md#p-13--a-burst-of-disconnects-left-users-online-cor-2)
- **"Too many connections" can be a client-side pool limit.** redis-py's pool allows 100 per process and raises
  instead of waiting. Read the library before tuning the server.
- **Port 5432 on this Mac belongs to a Homebrew Postgres 14**, not the Docker one, and it's too old for Django 6.1.
  Stop it (`brew services stop postgresql@14`) or map Docker to another port. → [P-04](docs/learning-journal/problems-and-solutions.md#p-04--makemigrations---check-warned-it-couldnt-connect-to-postgres)

## Working with Claude Code

- **Claude can't change its own permissions or the branch protection.** Auto mode blocks it, by design. You do
  those (`/permissions`, GitHub settings). → [P-03](docs/learning-journal/problems-and-solutions.md#p-03--claude-codes-auto-mode-refused-the-remote-change-and-a-push)
- **Verify claims before writing them down.** We had to correct two: a "FastAPI decision" that didn't exist in the
  docs, and "redis changed because of Python 3.13" (really: pip-compile kept the old pin).
- **An audit is only as current as the commit it was run on.** Record that commit, and re-check before acting on old findings.
