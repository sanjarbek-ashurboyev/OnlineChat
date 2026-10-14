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
- **Locally, `make test` runs with your `.env`'s `DEBUG` (True); CI runs with it off.** A setting inside
  `if not DEBUG:` doesn't exist in your local tests. → [P-35](docs/learning-journal/problems-and-solutions.md#p-35--a-production-only-setting-was-missing-from-the-local-tests)
- **`DJANGO_DEBUG` is `True`/`False`, not `1`/`0`.** Anything else means production mode, including locally.
- **The dev fallback `SECRET_KEY` exists only when `DEBUG` is on.** Never add a fallback that also applies in production.
- **Django loads many dependencies by *string* in `settings.py`** (`INSTALLED_APPS`, `CHANNEL_LAYERS`, `CACHES`).
  Searching for `import` misses them.

## Tests

- **Tests whose consumers touch the database must use `TransactionTestCase`.** With `TestCase`, Channels closes
  the test's connection on Postgres. SQLite hides it. → [P-12](docs/learning-journal/problems-and-solutions.md#p-12--websocket-tests-passed-on-sqlite-but-failed-on-postgres)
- **Green on SQLite is not green on Postgres.** The `test-postgres-redis` CI job is the real check.
- **After inserting a test class into a file, list `^class|def test_` to check every test is in the class you meant.**
  A class dropped mid-file silently adopts the tests below it (T-04 did this to two `MessagingTests` tests).
- **In zsh, never name a variable `path`.** It's tied to `PATH`; `for path in ...` wipes it, and every later
  command is "not found" (session 019).
- **macOS has no `timeout` command.** `timeout 40 cmd` fails with "command not found", so the command never runs.
  Use Python's `subprocess.run(..., timeout=40)` instead.
- **"0 tests ran" is not "tests pass".**
- **Browser tests (`chats/test_browser.py`) skip on `make test`.** Run them with Docker up:
  `python manage.py test chats.test_browser`. A skip is not a pass: CI sets `REQUIRE_BROWSER_TESTS=True`, which turns
  any skip into an error ([decision 012](docs/learning-journal/decisions/012-required-browser-tests.md)).
- **Never `assertIn`/`assertNotIn` against `os.environ`.** The failure message prints every variable, secrets
  included, into the log. Assert on `os.environ.get(name)` (session 025).
- **If `setUpClass` fails half-way, `tearDownClass` never runs.** Register each undo with `cls.addClassCleanup`
  before the step it undoes. → [P-33](docs/learning-journal/problems-and-solutions.md#p-33--the-schema-guessed-and-a-broken-browser-passed-as-a-skip)
- **A schema warning is a wrong line in the API contract.** `root/test_schema.py` fails on any; fix the cause
  (a type hint, `@extend_schema`), don't silence it.
- **macOS spawns processes, Linux forks them.** Code that starts a process can pass on the Mac and fail in CI.
  Reproduce with `multiprocessing.set_start_method('fork', force=True)`. → [P-22](docs/learning-journal/problems-and-solutions.md#p-22--browser-tests-passed-on-the-mac-but-never-connected-in-ci)
- **After an `await` in `app.js`, the user may even have signed out.** `api()` drops answers from an earlier
  session (`state.session`); new async code must go through it or check the session itself. → [P-29](docs/learning-journal/problems-and-solutions.md#p-29--logout-didnt-stop-the-previous-sessions-work)
  Check it **before** acting on an answer (a refresh, a retry), not only before using it. → [P-34](docs/learning-journal/problems-and-solutions.md#p-34--a-late-answer-acted-for-the-wrong-account-sent-twice-or-left-a-gap)
- **A load-test verdict ignores `server_errors`.** 169 error frames still gave "OK" (session 027). Read that column.
- **After an `await` in `app.js`, the user may have moved on.** Check the answer still belongs to what's on screen
  before drawing it. → [P-21](docs/learning-journal/problems-and-solutions.md#p-21--four-frontend-bugs-with-no-tests-to-catch-them)
- **In a `subTest` loop, keep every assertion of a case inside its `with self.subTest(...)`.** One outside it ends
  the test at the first failure, and the later cases never run.
- **`page.evaluate` waits for a promise you return.** If the test holds that promise's request (`page.route`),
  it deadlocks. Start it with `void loadChats()` instead (session 021).
- **In a browser test, don't call code that uses `async_to_sync` from the test thread** (e.g. a view that
  broadcasts). Playwright's loop runs there, so it raises; our view's `except` hid it. Change the database directly.
- **Writing Python code from a Python script doubles the escaping.** A test regex became `\\?` and never matched.
  `grep` the written file for the pattern before trusting it (session 023).
- **Playwright's `has_text='User 2'` is a substring match:** it also finds "User 20". Use `re.compile('^User 2$')`
  when names share a prefix; a "strict mode violation" is the sign (session 024).
- **A Playwright route handler must be a Python function**, not a built-in like `held.append`: wrap it in a lambda.
- **Write the failing test first, and watch it fail.** When mocking, also assert the mock was called
  (`assert_awaited_once()`); otherwise the test can pass without testing anything.

## Dependencies

- **`pip-compile` keeps existing pins.** Use `--upgrade` or `--upgrade-package NAME` to move on. Don't
  explain a version change before checking this. → [session 006](docs/learning-journal/sessions/006-syncing-with-github.md)
- **Compile with Python 3.13, the version CI uses.**
- **Prove an install in a fresh virtualenv.** Your daily `.venv` hides missing packages. → [P-07](docs/learning-journal/problems-and-solutions.md#p-07--development-and-a-fresh-install-would-use-different-postgres-drivers)
- **Edit `requirements.in`, never `requirements.txt`.**

## Security

- **DRF's `NUM_PROXIES` unset means "trust `X-Forwarded-For`"**, not "no proxy". We set it from
  `DJANGO_NUM_PROXIES` (default 0). Count proxies correctly when deploying. → [P-25](docs/learning-journal/problems-and-solutions.md#p-25--a-forged-x-forwarded-for-header-reset-the-login-limit)
- **A leaked secret must be rotated.** Deleting it from git history doesn't help: clones keep it.
- **"No leaks found" only means "nothing matched".** gitleaks' built-in rules missed our real Django key.
  Test a scanner on a planted secret before trusting it. → [P-11](docs/learning-journal/problems-and-solutions.md#p-11--gitleaks-built-in-rules-missed-our-real-leaked-key)
- **REST and the WebSocket are two doors to the same actions.** Any auth check or limit added to one needs the
  other too, with a test for each. → [P-20](docs/learning-journal/problems-and-solutions.md#p-20--two-doors-one-lock-auth-and-rate-limits-only-on-one-transport)
- **`loadtest/tokens.json` holds live login tokens.** It's gitignored; keep it that way.

## Profiles and chat refreshes

- **`on_commit` is not a concurrency lock.** Reload and lock the profile row before replacing its avatar; save
  only submitted fields, and log cleanup errors after commit. → [PR #34 follow-up](docs/learning-journal/sessions/026-pr34-followups.md)
- **Refreshing numbered pages needs ids and missing-page recovery.** Pages can overlap, disappear, or exclude a
  lookup-opened chat; test all three. → [PR #34 follow-up](docs/learning-journal/sessions/026-pr34-followups.md)

## Load testing

- **Near the ceiling one run proves little.** The same code was healthy at 2,000 in one run and failed at 1,750 in the
  next. Compare Postgres's counters, and interleave before/after runs. → [P-37](docs/learning-journal/problems-and-solutions.md#p-37--the-same-code-was-healthy-at-2000-in-one-run-and-failed-at-1750-in-the-next)
- **Give the server time to finish before checking what it left behind.** Stopping Daphne right after the tester
  exits cut 3,000 disconnects short, and Redis looked full of leftovers the app never left. → [P-36](docs/learning-journal/problems-and-solutions.md#p-36--thousands-of-leftovers-in-redis-that-the-app-never-left)

- **Fake data must carry a marker real data *can't* have** (seed users use the invalid `+998000` range), and a
  "replace" must check its arguments first and delete inside the same transaction. → [P-24](docs/learning-journal/problems-and-solutions.md#p-24--the-load-test-seed-command-could-delete-real-accounts)

- **Before trusting a load test's "OK", make it fail on purpose** (e.g. block every pair so nothing is delivered).
  Our tester once passed a step with zero echoes. → [P-23](docs/learning-journal/problems-and-solutions.md#p-23--the-load-tester-could-pass-a-step-with-zero-echoes)

## Runtime and infrastructure

- **"Check, then act" in two Redis calls is a race** (8 of 8 sockets got past a limit of 5). Do it in one step:
  a Lua script. → [P-27](docs/learning-journal/problems-and-solutions.md#p-27--five-sockets-opened-at-once-let-eight-in)
- **A long-lived connection must re-check its rights.** Sockets close at token expiry (4401) and within 60 s of an
  account being disabled ([decision 006](docs/learning-journal/decisions/006-socket-rights-end-with-the-token.md)).
- **Cleanup code must not depend on every step succeeding.** A failing `group_discard` used to skip "mark
  offline". Log the failure, then do the important step anyway. → [P-13](docs/learning-journal/problems-and-solutions.md#p-13--a-burst-of-disconnects-left-users-online-cor-2)
- **In Channels, `close(code)` before `accept()` is an HTTP 403: the browser sees 1006, never your code.** Accept, then
  close. The test client shows the code either way, so assert the handshake succeeded. → [P-16](docs/learning-journal/problems-and-solutions.md#p-16--our-websocket-close-codes-never-reached-the-browser-cor-5)
- **The channel layer is at-most-once.** Never treat the live stream as complete: after a reconnect, fetch the gap from Postgres.
- **A quiet socket is a test case.** redis-py 8's default 5 s socket timeout crashed every idle consumer (channels-redis
  blocks for 5 s). Major bumps can change *defaults*: read the changelog. → [P-17](docs/learning-journal/problems-and-solutions.md#p-17--every-quiet-websocket-crashed-after-5-seconds-redis-py-8)
- **One TTL for a group, renewed by any member, means a dead member never expires.** Presence now scores each socket
  with its own last ping. → [P-18](docs/learning-journal/problems-and-solutions.md#p-18--leftover-presence-entries-lived-as-long-as-any-other-tab)
- **A fake must behave like the real thing, and something must test the real thing.** `FakeRedis` choked on Redis's
  `(` exclusive-range syntax, and no test ran presence against real Redis until session 013.
- **A load test also measures the network.** Over an iPhone hotspot, ping p95 was 366 ms at 100 users, and the "server"
  failed at 300. From the server machine itself it passed with 90 ms. Compare before blaming the server. → [P-19](docs/learning-journal/problems-and-solutions.md#p-19--the-second-machine-baseline-measured-the-hotspot-not-the-server)
- **"Too many connections" can be a client-side pool limit.** redis-py's pool allows 100 per process and raises
  instead of waiting. Read the library before tuning the server. Our channel layer now waits (`chats/layers.py`, session 033).
- **Check what serves port 6379 before trusting a Redis result** (`lsof -nP -iTCP:6379 -sTCP:LISTEN`). A Homebrew
  Redis used to take it, and `docker compose stop redis` then didn't take the app's Redis down. To test an outage,
  point `REDIS_PORT` at a free port instead. → [P-26](docs/learning-journal/problems-and-solutions.md#p-26--stopping-dockers-redis-didnt-stop-the-apps-redis)
- **"Up (healthy)" in `docker compose ps` isn't "reachable".** Check the `PORTS` column shows `0.0.0.0:6379->6379`.
  Our Redis came back unpublished after a stop/start while another Redis held the port. → [P-28](docs/learning-journal/problems-and-solutions.md#p-28--dockers-redis-came-back-without-its-port)
- **"Connection refused" on 5432/6379 and `docker compose ps` can't reach the daemon: Docker Desktop isn't running**
  (it stops after a restart). `open -a Docker`, then wait for both services to be healthy (session 025).
- **A connection pool hands out dead connections after Postgres restarts, and `CONN_HEALTH_CHECKS` alone isn't enough**:
  the pool's default check timed out with 10 dead ones. Our check drops them all (`root/db.py`). → [P-38](docs/learning-journal/problems-and-solutions.md#p-38--conn_health_checks-still-failed-with-a-pool-full-of-dead-connections)
- **Never test pooled connections one by one on a request's thread** (`pool.check()`): one that hangs stalls that
  request and empties the pool for everyone. `pool.drain()` closes them and reopens in the background. → [P-44](docs/learning-journal/problems-and-solutions.md#p-44--one-hung-connection-stalled-every-request-during-the-pools-cleanup)
- **Port 5432 on this Mac belongs to a Homebrew Postgres 14**, not the Docker one, and it's too old for Django 6.1.
  Stop it (`brew services stop postgresql@14`) or map Docker to another port. → [P-04](docs/learning-journal/problems-and-solutions.md#p-04--makemigrations---check-warned-it-couldnt-connect-to-postgres)

## Working with Claude Code

- **Claude can't change its own permissions or the branch protection.** Auto mode blocks it, by design. You do
  those (`/permissions`, GitHub settings). → [P-03](docs/learning-journal/problems-and-solutions.md#p-03--claude-codes-auto-mode-refused-the-remote-change-and-a-push)
- **Verify claims before writing them down.** We had to correct two: a "FastAPI decision" that didn't exist in the
  docs, and "redis changed because of Python 3.13" (really: pip-compile kept the old pin).
- **An audit is only as current as the commit it was run on.** Record that commit, and re-check before acting on old findings.
