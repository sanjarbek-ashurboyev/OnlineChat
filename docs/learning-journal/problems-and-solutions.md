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
  - **Follow-up (session 033):** channels-redis now gets a `BlockingConnectionPool` (`chats/layers.py`), which waits
    for a free connection. 3,000 sockets closing at once: 2,881 failed `group_discard`s and 2,881 dead group entries
    before, 0 and 0 after (cleaned up within ~3 s).
- **Verified:**
  - A test (`test_a_failed_group_discard_still_marks_the_user_offline`) made `group_discard` raise
    `MaxConnectionsError`. It failed before the fix and passes after.
  - 54/54 tests pass.
  - **Not verified yet:** the acceptance check "no presence leftovers after the load test's end-of-run
    disconnects". That needs the local stack running (Docker), and is planned with the baseline load test.
- **Lesson:** cleanup code must not depend on every step succeeding. Do the most important step (mark offline)
  regardless, and log the rest. A "too many connections" error is often a *client-side pool* limit, not the server's.

## P-14 · Dependabot PRs that could never be merged

- **Sessions:** [007](sessions/007-t11-tests-and-ci.md), [008](sessions/008-t02-disconnect-marks-offline.md)
- **Observed:** after PR #14, Dependabot PR #12 (aiohttp for the load test) sat with two required checks
  "expected" forever. `@dependabot rebase` got the reply: *"The dependabot.yml entry that created this PR has been
  deleted so this PR can't be rebased."*
- **Root cause (Confirmed, Dependabot's own reply):**
  1. `dependabot.yml` had both a `/` entry (which already covers `loadtest/`) and a `/loadtest` entry, so the
     same update arrived twice: #12 from `/loadtest`, #13 from `/`.
  2. PR #14 removed the `/loadtest` entry, which **orphaned #12**: Dependabot no longer manages it, so it can't rebase it.
  3. The advice was to close **#13**, the one from the entry we *kept*. Closing a Dependabot PR makes it **skip
     that release** ("I won't notify you again about this release") and **deletes its branch**, so
     `@dependabot reopen` did nothing.
  4. Without a rebase, #12 never ran the two jobs added in #14, and the ruleset requires them.
- **Fix:** made the same one-line change ourselves in PR #16 (auto-merged after 4 green checks), and closed #12
  with a comment pointing to #16.
- **Lesson:** before removing a Dependabot config entry, close the PRs it created. When two PRs duplicate each
  other, keep the one from the entry that stays. Closing a Dependabot PR is not neutral: it skips that version.


## P-15 · A commit pushed to a PR after auto-merge never reached `main`

- **Session:** [010](sessions/010-t04-websocket-input-and-rate-limits.md)
- **Observed:** I pushed a second commit (a fix to the `progress.md` learning tracker) to the T-03 branch and
  reported "PR #18 passed all 4 checks again". When asked to merge, `gh pr merge 18` answered *"was already
  merged"*. The merged head was `df0691e`, the first commit. The fix `02337ea` was on the branch, but not on `main`.
- **Root cause (Confirmed, from timestamps):** auto-merge was on for PR #18. It merged at 18:42:21, as soon as the
  first commit's checks passed. My push came later, onto a branch whose PR was already closed. The "green checks"
  I read were for that orphaned commit, which no open PR contained.
- **Fix:** cherry-picked the commit onto the next branch (`t-04-ws-input-validation`), so it ships with the T-04 PR.
- **Lesson:** with auto-merge on, a PR can close at any moment after its checks pass. Before pushing to a PR
  branch, run `gh pr view N --json state`. If it says `MERGED`, put the change on a new branch from `main`.

## P-16 · Our WebSocket close codes never reached the browser (COR-5)

- **Session:** [011](sessions/011-t09-gap-fetch-and-jitter.md)
- **Observed:** the client has a branch for close code 4401 ("token expired: refresh, then reconnect"), and T-04
  added 4429 ("too many sockets"). The audit suspected browsers never see these codes.
- **Root cause (Confirmed, Daphne source and a test):** the consumer called `close(code=...)` **before**
  `accept()`. In `daphne/ws_protocol.py:191-195`, a `websocket.close` that arrives while the socket is still
  connecting calls `serverReject()`: an HTTP 403, with no close code. A browser reports that as 1006. Only after
  `accept()` does a close carry our code (`serverClose(code=...)`). The new `refused()` test helper failed with
  "refused before the handshake" for both 4401 and 4429.
- **Fix:** `InboxConsumer.refuse(code)` accepts, then closes. A frame that slips in between is ignored
  (`self.refused`), and a test covers that too.
- **Side effect found in review:** now that 4401 really arrives, the client's "refresh, then reconnect at once"
  branch can run. If the server kept refusing, that would be a tight loop, so it goes through the jittered backoff too.
- **Lesson:** in Channels, refuse a socket by accepting and then closing, when the client needs to know *why*.
  Test that the close comes *after* the handshake, not just that a code exists: Channels' test client reports the
  code either way.

## P-17 · Every quiet WebSocket crashed after 5 seconds (redis-py 8)

- **Session:** [012](sessions/012-redis-socket-timeout.md)
- **Observed:** during the T-09 browser check, the server log showed `Exception inside application: Timeout reading
  from localhost:6379`. The first server run had 4 sockets and 3 crashes. Each crash skipped `disconnect()`, so its
  presence entry stayed in Redis. After 5 leftovers, the 5-socket cap (T-04) refused the user: 142 connects in about 2 minutes.
- **Root cause (Confirmed, by reproduction and library source):**
  1. channels-redis waits for a socket's next message with `BZPOPMIN key 5` (`brpop_timeout = 5`,
     `channels_redis/core.py:104`): "block up to 5 s on the server".
  2. redis-py 8 added a default `socket_timeout` of 5 s (`redis/_defaults.py:7`). redis-py 7 had none.
  3. The client gives up at 5.0 s, just before the server's 5 s reply arrives, and raises `TimeoutError`. The
     exception escapes the consumer, which dies.
  4. Reproduced outside Django: a 5 s `bzpopmin` on an empty key raised `TimeoutError` at 5.01 s, 3 times out of 3,
     with default settings, and returned normally with `socket_timeout=None`.
  5. We got redis-py 8 from a Dependabot PR (`redis==7.4.1` → `8.1.0`) merged on 2026-10-10.
- **Why CI missed it:** the SQLite job uses the in-memory channel layer. The Postgres + Redis job never left a
  socket quiet for 5 s.
- **Fix:** give the channel layer's connection `socket_timeout: 10` in `CHANNEL_LAYERS`, so reads outlast the 5 s
  wait. New test `chats/test_channel_layer.py`: a quiet channel must not raise a Redis error. It failed first
  (`redis.exceptions.TimeoutError` at 5.02 s), and passes now.
- **Not fixed here:** a consumer that crashes still leaks its presence entry until the 90 s TTL expires.
- **Lesson:** a dependency's *default* can change in a major version, even when your code doesn't. Read the
  changelog of a major bump, and test long-lived connections *idle*, not only busy.

## P-18 · Leftover presence entries lived as long as any other tab

- **Session:** [013](sessions/013-presence-leak.md)
- **Observed:** in session 011's browser check, leftover presence entries from crashed consumers kept counting
  toward the 5-socket cap, and the user was locked out (4429) until they expired. Session 012 noted it as a follow-up.
- **Root cause (Confirmed, by tests):** presence was one Redis **set** per user with **one TTL for the whole set**,
  and every ping renewed that TTL (`presence.refresh(user_id)`). A socket that dies without `disconnect()` running
  (consumer crash, killed process, every deploy) leaves its entry behind. As long as *any* other tab pinged, the
  set never expired, so the leftover counted toward the cap, and toward "online", indefinitely. The old design's
  comment ("a crashed worker's leftovers expire") was only true when the user had no other tab open.
- **Fix:** a sorted set (`online:<id>`) scoring each socket with its own last-ping time. Counts include only
  entries under 90 s old, and `socket_count` also deletes older ones. `refresh()` now takes the channel name and
  renews only that socket. New key name, because the new commands fail on the old plain-set keys (`WRONGTYPE`).
- **Tests:** 5 unit tests with a frozen clock, a consumer test (5 dead entries plus a pinging tab must not
  block a new socket), and one test against real Redis. They failed first: `refresh()` couldn't target one
  socket, and a user whose only socket died stayed online.
- **Lesson:** one expiry for a whole group, renewed by any member, means a dead member never expires.

## P-19 · The second-machine baseline measured the hotspot, not the server

- **Session:** [014](sessions/014-baseline-load-test.md)
- **Observed:** with the generator on a second Mac, the realistic profile passed at 200 users and failed at 300
  (message p95 616 ms). The server's CPU never passed about 30% of one core, and there were no server errors during the steps.
- **Root cause (Confirmed, by experiment):** both Macs were on an **iPhone Personal Hotspot** (`172.20.10.x`). Every
  packet between them makes two wireless hops through the phone. Even at 100 users, the lightest frame (ping) had a
  p95 of 366 ms. Running the **same** 300-user step from the server Mac itself (no network in between) gave
  message p95 **90 ms** and ping p95 **44 ms**, a pass, even though the generator then competed with the server for CPU.
- **Fix:** none in code. The result is recorded as network-limited, and the server's own ceiling was measured
  separately (healthy at 750, cliff at 1,000; with the fixed tester in session 028: healthy at 500, failing at 750).
- **Lesson:** "run the generator on another machine" assumes a good network between them. Measure the network,
  or compare with a local run, before blaming the server.

## P-20 · Two doors, one lock: auth and rate limits only on one transport

- **Session:** [015](sessions/015-codex-review-fixes-1-2.md)
- **Observed:** an external review (OpenAI Codex) reported that (1) a disabled account could still open the inbox
  WebSocket with an unexpired token, and (2) `POST /chats/<id>/messages/` had no rate limit, so the socket's limit
  (T-04) could be skipped by sending over REST.
- **Root cause (Confirmed, by tests):** the app has two ways to reach the same actions, REST and the WebSocket,
  and each protection was added to only one of them. SimpleJWT's REST authentication checks `is_active`. Our own
  socket middleware (`chats/middleware.py`) only checked the token's signature and expiry, then loaded the user
  without that check. T-04 limited frames on the socket, and nobody added a REST limit for the same action.
  The new socket test errored (the socket was accepted) and the throttle test failed (`201 != 429`) before the fix.
- **Fix:** the middleware looks the user up with `is_active=True`. Message sends over REST have a `message_send`
  throttle of 60/min per user, the same sustained rate as the socket.
- **Lesson:** list every path to an action before calling it protected, and write one test per path.

## P-21 · Four frontend bugs, with no tests to catch them

- **Session:** [016](sessions/016-codex-review-frontend-fixes.md)
- **Observed:** a Codex review reported four bugs in `assets/app.js`. Each was reproduced by a Playwright test
  before the fix: chat A's message showed up in chat B (`['from B', 'from A']`); "load older" showed `m03, m02, m01`;
  chats after the first 50 couldn't be reached (no button, and looking one up did nothing); a blocked send
  emptied the composer.
- **Root causes (Confirmed, by tests):**
  - `loadHistory` drew its answer after `await` without checking that the chat was still open. `openChat` then
    also sent a read receipt for that chat, marking messages read that never reached the screen.
  - Older pages were reversed to oldest-first and then prepended one by one, which reversed them again.
  - `loadChats` read `data.results` and ignored `data.next`, and the lookup opened a chat only if it was in that list.
  - The composer was cleared as soon as the frame was sent, before the server accepted it.
- **Fix:** an `opened` counter (stale answers are dropped); prepend older pages newest-first; a "Show more chats"
  button, polls that keep extra pages, and the lookup adds the chat it gets back; the text stays until the server's
  echo arrives, and an error leaves it in place.
- **Lesson:** code with no tests collects bugs unnoticed. Code that `await`s must re-check the world afterwards.

## P-22 · Browser tests passed on the Mac but never connected in CI

- **Session:** [016](sessions/016-codex-review-frontend-fixes.md)
- **Observed:** all 6 browser tests passed locally, then failed in CI's `test-postgres-redis`, each waiting for
  `#conn-state.is-open` ("element(s) not found"): the page's WebSocket never connected.
- **Root cause (Confirmed, by experiment; the exact mechanism is a Hypothesis):** `ChannelsLiveServerTestCase` starts
  Daphne with `multiprocessing`. macOS starts a new process with **spawn** (a fresh Python). Linux uses **fork** (a copy
  of the test process, with its open connections and state). Forcing fork locally reproduced the CI failure exactly;
  forcing spawn fixed it. Which inherited thing breaks the server (a Postgres or Redis connection, or the event loop)
  was not traced.
- **Fix:** the browser test class sets the start method to `spawn` for its own run and restores it afterwards.
  With fork as the default, as in CI, the full suite passed locally: 89 OK.
- **Lesson:** "passes on my machine" can depend on the OS's defaults. When CI and local disagree, list what differs
  (OS, Python version, settings) and test each difference on purpose.

## P-23 · The load tester could pass a step with zero echoes

- **Session:** [017](sessions/017-loadtest-verdict.md)
- **Observed:** a Codex review said `loadtest/run.py` could overstate capacity. Reproduced with the old tester against
  a local server where every pair was blocked (so the server rejects every message): **194 sent, 0 echoes, verdict OK**.
  Killing the server during step 1 made the old tester report step 2 as "20/40 connected" (all were dead) and
  "2/1 messages lost".
- **Root causes (Confirmed, by those runs):**
  - `(row['message_p95_ms'] or 0) > limit`: no samples became 0 ms, which always passes.
  - A message counted as lost only once it was older than `--message-timeout` *at the moment of the summary*.
    In a short step nothing was old enough, so nothing was lost.
  - `connected = len(users) - drops`, but `drops` was reset with each step's new `Stats`. Earlier drops were forgotten.
  - Messages sent during the ramp stayed pending after the counters were reset, so a step could lose more than it sent.
  - Only the sender's echo was measured. Delivery to the recipient wasn't checked.
  - The limits were looser than the plan: 500 ms and 1,000 ms p95, 1% errors (plan: 300 ms, 300 ms, 0.1%).
- **Fix:** the pass/fail rules moved to `loadtest/verdict.py` (unit tested), with "no measurements" as a failure and
  the plan's limits as defaults. Each step ends with a drain: sending pauses, the tester waits for in-flight messages,
  and what's missing is lost. Online users are counted from each socket's own `closed` flag. Delivery to the
  recipient is measured. Rerunning the same experiments: 205/205 no echo → FAIL; step 2 → 0/40 connected.
- **Lesson:** a test that can't fail proves nothing. Feed it a broken system and check it says so.

## P-24 · The load-test seed command could delete real accounts

- **Session:** [018](sessions/018-loadtest-seed-safety.md)
- **Observed:** Codex audit H-05: in an isolated database, an ordinary account matching the seed markers was deleted by
  `loadtest_seed --users 0`, which then failed with `CommandError`. Reproduced here by a test: a user registered as
  `+998990000001` / `loadtest` disappeared after `loadtest_seed --delete`.
- **Root causes (Confirmed, by the failing tests):**
  - Seed users were recognised by `+998990` + first name `loadtest`. `phonenumbers` says `+998990…` numbers are
    valid, and anyone can choose the name, so a real user could match both.
  - The delete ran before the arguments were checked.
  - The delete ran outside the transaction that creates the replacements.
- **Fix:** the seed range is `+998000…`, which `phonenumbers` (and so registration) rejects. Arguments are checked
  first. The delete runs inside `transaction.atomic()` with the create. 5 tests in `chats/test_loadtest_seed.py`.
- **Lesson:** fake data needs a marker real data *can't* have. And never delete anything before you know the
  operation can finish.

## P-25 · A forged `X-Forwarded-For` header reset the login limit

- **Session:** [019](sessions/019-account-security.md)
- **Observed:** Codex audit H-02: 21 failed logins from one `REMOTE_ADDR`, each with a different `X-Forwarded-For`,
  all answered 401; the 21st should be 429. Reproduced by a test, and against `runserver` with `curl`.
- **Root cause (Confirmed, by reading DRF 3.x `BaseThrottle.get_ident` and the test):** with `NUM_PROXIES` unset,
  DRF returns the whole `X-Forwarded-For` header as the client's identity whenever it's present. Session 009 had
  read "set `NUM_PROXIES` when a proxy arrives" as "not needed until then", but unset means "trust the header".
- **Fix:** `REST_FRAMEWORK['NUM_PROXIES']` from `DJANGO_NUM_PROXIES`, default `0` (use `REMOTE_ADDR`).
  [Decision 005](decisions/005-client-ip-and-throttle-outages.md).
- **Lesson:** a library default is a choice someone made for you. Find out what "unset" does before relying on it.

## P-26 · Stopping Docker's Redis didn't stop the app's Redis

- **Session:** [019](sessions/019-account-security.md)
- **Observed:** to test login with Redis down, I ran `docker compose stop redis`. Login still answered 429, so the
  throttle was still counting.
- **Root cause (Confirmed, `lsof -iTCP:6379 -sTCP:LISTEN`):** a Homebrew Redis (`brew services`, `redis-server`) listens
  on `127.0.0.1:6379`. `.env` points at `localhost:6379`, so the app talks to Homebrew's Redis, not Docker's. Same
  pattern as the Homebrew Postgres in [P-04](#p-04--makemigrations---check-warned-it-couldnt-connect-to-postgres).
  Not checked: which Redis earlier "real Redis" test runs used. Probably Homebrew's too.
- **Fix (for the test):** started a second server with `REDIS_PORT=6390`, where nothing listens. Old code: 500;
  new code: 401. The Homebrew service was left running; whether to keep it is your call.
- **Lesson:** before testing "service X is down", check which process the app is really connected to.

## P-27 · Five sockets opened at once let eight in

- **Session:** [020](sessions/020-websocket-hardening.md)
- **Observed:** Codex audit M-01: 8 simultaneous connections for one user were all admitted, despite the 5-socket
  limit. Reproduced by a test: 8 connects through `asyncio.gather` → **8 admitted** (expected 5).
- **Root cause (Confirmed, by the test):** `connect()` counted the user's sockets (`presence.socket_count`), then
  awaited `group_add` and `accept`, and only then added itself (`mark_online`). All 8 counted before any of them
  added, so all saw fewer than 5. The code even said so: "A soft cap".
- **Fix:** `presence.admit()` prunes, counts and adds in one Lua script. Redis runs a script alone, so nothing
  can run between the count and the add. Real-Redis test: 8 threads at once → exactly 5.
- **Lesson:** "check, then act" across two separate calls is a race. Make the check and the act one step.

## P-28 · Docker's Redis came back without its port

- **Session:** [020](sessions/020-websocket-hardening.md)
- **Observed:** on the real-services settings almost every consumer test failed with
  `Connect call failed ('127.0.0.1', 6379)`. `docker compose ps` showed `onlinechat_redis` up, but with ports
  `6379/tcp` instead of `0.0.0.0:6379->6379/tcp`. The Homebrew Redis had been stopped meanwhile, so nothing served
  `localhost:6379`.
- **Root cause (Hypothesis):** in session 019 I ran `docker compose stop redis` / `start redis` while the Homebrew
  Redis held `127.0.0.1:6379`. Docker probably couldn't publish the port then, and the restarted container stayed
  unpublished. Not reproduced.
- **Fix:** `docker compose up -d --force-recreate redis` (data stays in its volume). Now Docker's Redis serves
  `localhost:6379`, as `compose.yaml` intends.
- **Lesson:** "Up (healthy)" says the service runs, not that you can reach it. Check the `PORTS` column.

## P-29 · Logout didn't stop the previous session's work

- **Session:** [021](sessions/021-frontend-session-lifecycle.md)
- **Observed:** Codex audit H-04, reproduced by browser tests on the old `app.js`: a token refresh that finished
  after logout saved its token again (`localStorage.access` set on the login screen); a chat-list answer from
  before logout showed User 2's chat to the next account; and a send still waiting at logout blocked the next
  account's first message.
- **Root cause (Confirmed, by those tests):** `logout()` only closed the socket and cleared tokens and the chat
  list. Requests, the refresh call, the reconnect timer and `state.sending` belonged to no session, so when they
  finished they wrote into whatever session was current.
- **Fix:** `state.session`, bumped by `logout()`; `api()` and `refreshAccess()` drop answers for an older session.
  `logout()` also cancels the reconnect and startup timers, detaches every socket handler, and clears the pending
  send, open chat, rows and composer.
- **Lesson:** anything async that can outlive a session has to know which session it belongs to.

## P-30 · Read receipts covered messages nobody had seen

- **Session:** [022](sessions/022-message-receipts.md)
- **Observed:** Codex audit M-06, M-07, M-08, reproduced by tests: a read marked a message that arrived after the
  screen was drawn (`2 != 1`); a read over REST reached no socket; one receipt ticked every outgoing message; and a
  receipt missed while offline was never repaired.
- **Root cause (Confirmed, by the tests):** "read" meant "everything in this chat, now", not "what I have on screen".
  The socket and REST had two copies of the update, and only the socket told the sender. Nothing let a client ask
  how far the other person had read.
- **Fix:** a **read-up-to boundary**: the client sends the newest message id on screen; `chats.consumers.mark_read()`
  (shared by both doors) marks only up to it, and `broadcast_read()` tells both sides. The chat list carries
  `peer_read_up_to`, so the 45 s poll or a reconnect repairs missed ticks.
  [Decision 008](decisions/008-read-up-to-boundary.md).
- **Lesson:** "read" is a statement about the screen, so the screen must say how far it got.

## P-31 · Messages out of order, holes never filled, pages repeated or skipped

- **Session:** [023](sessions/023-message-ordering.md)
- **Observed:** Codex audit M-03, M-09, M-10, M-11, reproduced by tests: a live message that beat the history was drawn
  above it; a message lost live before a later one was never fetched after a reconnect; one failed "Load older" skipped
  a page (70 rows instead of 100); two clicks on "Show more chats" fetched page 2 twice; and after 50 new messages, the
  second history page repeated the first.
- **Root causes (Confirmed, by the tests):**
  - rows were appended in arrival order, not sorted;
  - catch-up started after the newest message *seen*, not after a point known to be complete;
  - the page counter moved before the request succeeded, and nothing stopped two requests at once;
  - history used offset pages over a list that grows at the top.
- **Fix:** rows are inserted by id; `syncedUpTo` is a boundary only fetches move, with catch-up on every connect;
  one request at a time, pointer moved on success; history pages by cursor
  ([decision 009](decisions/009-cursor-pagination-for-history.md)).
- **Lesson:** a list fed from several sources needs an order key and a completeness boundary, not trust in arrival order.

## P-32 · The chat list and the poll showed what other screens had hidden or changed

- **Session:** [024](sessions/024-privacy-and-uploads.md)
- **Observed:** Codex audit M-13, M-14, M-15, M-16, reproduced by tests: the chat list returned the photo, online
  status and last seen of someone who had blocked the user (their profile answers 404); a 1-pixel PNG with 2 MiB of
  junk, and a 4097 × 1 image, were accepted; replacing a photo left both files on disk, and removing it or deleting the
  account left the file; after the 45 s poll, a chat on page 2 kept its unread badge and the open chat's header its old
  name.
- **PR #34 follow-up (Confirmed):** [session 026](sessions/026-pr34-followups.md) tests exposed five
  remaining cases: a stale name-only save destroyed a replacement avatar (and overlapping uploads
  left an orphan); a storage deletion exception escaped after saving; overlapping pages produced
  duplicate rows; lookup-opened chats outside the loaded pages never refreshed; a vanished last
  page made every poll reject with 404.
  The corrections are a locked reload plus limited fields for profile saves, logged cleanup errors,
  chat merging by id, a membership-checked `chat_id` refresh filter using the existing privacy
  serializer, and recovery to the remaining valid pages. These do not change token refresh or
  message acknowledgement/recovery code.
- **Root causes (Confirmed, by the tests):**
  - the block check lived in the profile view, not in the serializer that every user-shaped answer goes through;
  - the only check on an avatar was Pillow's "is this an image?";
  - nothing deleted a file when the row stopped pointing to it;
  - the poll fetched page 1 only, and the header was drawn once, in `openChat()`.
- **Fix:** `blocked_by` in the chat list's serializer context ([decision 010](decisions/010-blocked-peer-in-the-chat-list.md));
  byte and dimension limits in `ProfileSerializer.validate_avatar()`; signals that delete unused files after the commit
  ([decision 011](decisions/011-delete-avatar-files-after-commit.md)); the poll fetches every loaded page and redraws
  the header (`showPeer()`).
- **Lesson:** each rule has to hold everywhere the same data comes out or goes in, and anything drawn once needs
  something that redraws it.

## P-33 · The schema guessed, and a broken browser passed as a skip

- **Session:** [025](sessions/025-api-contract-and-browser-skips.md)
- **Observed:** Codex audit M-20 and M-22, reproduced by tests. The OpenAPI schema had 13 warnings, declared no
  authentication, typed `is_online` and `participant` as strings, gave the read endpoint no response body, and (with
  no warning) described `POST /chats/`, history pages and avatar uploads wrongly. A Chromium that failed to launch made
  the browser tests skip, so CI stayed green, and left `DJANGO_ALLOW_ASYNC_UNSAFE=true` behind.
- **Root causes (Confirmed, by the tests):**
  - drf-spectacular matches authenticators by exact class, so our subclass of `JWTAuthentication` was unknown;
  - method fields had no type, and the views described their input serializer as their output;
  - the generator reads `pagination_class`, which our view didn't set (the `paginator` property chose per request);
  - `setUpClass` caught every exception as "browser not downloaded" and restored the environment only on success.
- **Fix:** a `LastSeenJWTScheme` extension, type hints and `@extend_schema` where the generator can't see, separate
  request schemas, and a test that fails on any schema warning. `REQUIRE_BROWSER_TESTS=True` in CI makes skips errors
  ([decision 012](decisions/012-required-browser-tests.md)); undo steps are class cleanups registered before each step.
- **Lesson:** a check that can't fail (a warning nobody reads, a skip that counts as green) isn't a check.

## P-34 · A late answer acted for the wrong account, sent twice, or left a gap

- **Session:** [027](sessions/027-session-replay-and-recovery.md)
- **Observed:** four gaps Codex reproduced at `1abe93c`, each now a failing-first test:
  - a 401 for account A's profile update, arriving after B signed in, was refreshed with B's token and sent again
    (the server got the request twice, the second time as B);
  - after a lost echo, Enter during the history check sent the same message again (2 rows instead of 1);
  - a socket that became ready while the history loaded never caught up: a message between the history's snapshot
    and the socket was missing (1 row instead of 2);
  - every load-test read receipt lacked `up_to` and came back as an error frame: 169 errors for 167 messages.
- **Root causes (Confirmed, by the tests):**
  - `api()` checked the session after the refresh-and-retry step, not before it;
  - the timeout settled the send *before* the history check, not after;
  - `catchUp()` returned when there was no boundary yet, and nothing ran it later;
  - `loadtest/run.py` wasn't updated when `up_to` became required in session 022.
- **Fix:** the session check moved up to right after `fetch`; the send settles after reconciliation; `catchUpDue`
  remembers a skipped catch-up for after the history; the tester sends `up_to` (the message's id).
- **Lesson:** "after this `await`, is it still the same world?" applies to every step that acts on an answer, not
  only to drawing it. And a protocol change must update every client, the load tester included.

## P-35 · A production-only setting was missing from the local tests

- **Session:** [031](sessions/031-readyz.md)
- **Observed:** the test "a plain HTTP probe of `/readyz` is not redirected" still got a **301** after
  `SECURE_REDIRECT_EXEMPT` was added, even though the test turned `SECURE_SSL_REDIRECT` on.
- **Root cause (Confirmed, by rerunning with `DJANGO_DEBUG=False`: it passed):** the exemption was inside
  `if not DEBUG:` in `root/settings.py`. `root/settings_test.py` imports `root/settings.py`, which loads `.env`, and the
  local `.env` sets `DJANGO_DEBUG=True`. So locally the block never ran and the exemption didn't exist. In CI there's
  no `.env`, DEBUG is off, and the test would have passed: the same test, two results.
- **Fix:** the exemption moved out of the `if not DEBUG:` block. It's harmless with DEBUG on. The test passes both ways.
- **Lesson:** local tests and CI don't share `DEBUG`. Put settings a test relies on outside `if not DEBUG:`, or run the
  test both ways (`DJANGO_DEBUG=False make test`).

## P-36 · Thousands of "leftovers" in Redis that the app never left

- **Session:** [033](sessions/033-redis-pool-waits.md)
- **Observed:** after a load test with the fixed channel layer (0 errors in the log), Redis still held 2,990 presence
  keys with a member and thousands of group entries from that run, as if `disconnect()` had never run.
- **Root cause (Confirmed, by experiment):** my load-test script stopped Daphne (SIGTERM) the moment the tester exited.
  Daphne was still working through 3,000 disconnects, each needing several calls on the one thread (presence,
  `last_seen`), so most never ran. The same burst with a 30 s pause before stopping: **0 leftovers**; polled every
  second: all cleaned up within ~3 s.
- **Fix:** the script waits 30 s before stopping Daphne.
- **Lesson:** "check the state after the test" needs the server to have *finished* the test. And it's a real deploy
  concern too: stopping a process mid-burst skips cleanup (T-27, graceful WebSocket shutdown).

## P-37 · The same code was healthy at 2,000 in one run and failed at 1,750 in the next

- **Session:** [034](sessions/034-t15-last-seen-interval.md)
- **Observed:** one Daphne process, same steps, same 3,000-user seed. `54831d1` (session 033): healthy at 2,000.
  An hour later `fba1bbc` (the same code plus docs): message p95 416 ms at 1,750, a fail, and 500 failed connects at 3,000.
- **Ruled out (Confirmed):** database bloat. `pg_stat_user_tables` showed autovacuum current and at most 642 dead rows,
  after six reseeds.
- **Root cause (Hypothesis):** the Mac itself. The tester runs on it too, near its own limits at 2,000+ sockets, plus
  whatever else is running. Not measured.
- **Fix:** none in the app. In the method: compare Postgres's counters (work per message), which don't depend on how
  fast that run was, and interleave runs (A-B-A-B) before claiming a ceiling moved.
- **Lesson:** near the ceiling, a single before/after pair can't show a 250-user difference.


## P-39 · One refresh token, two parallel requests, two new tokens

- **Session:** [036](sessions/036-login-sessions.md)
- **Observed:** on `main` (`35eb53a`), two requests to `/auth/token/refresh/` with the same token both answered 200,
  and both new tokens kept working: 20 of 20 tries against a real Daphne, every time in a test that holds both
  requests at the same point.
- **Root cause (Confirmed, from SimpleJWT 5.5.1's code and the test):** "check, then act" in separate statements.
  Each request checks the blacklist (`SELECT`), then blacklists with `get_or_create`; the slower one gets the existing
  row back (`created=False`), which no one checks.
- **Fix:** a `LoginSession` row per login holds the id of the one usable refresh token; refresh swaps it with one
  `UPDATE ... WHERE refresh_jti = <presented>`, and 0 rows changed means 401 (decision 016).
- **Lesson:** `get_or_create` doesn't claim anything. Make the write carry the condition and read the row count.

## P-40 · Logout from a tab with an older token didn't end the login

- **Session:** [036](sessions/036-login-sessions.md)
- **Observed:** tab A renewed R0 → R1; tab B, still holding R0, logged out: 401, and R1 kept working. The same when B
  logged out while A's renewal was on its way back.
- **Root cause (Confirmed):** logout blacklisted *one token*, and R0 was already blacklisted by A's renewal. Nothing
  connected R0 and R1 as the same login.
- **Fix:** every refresh token of a login carries the login's id (`sid`); logout ends the session row, whichever of
  its tokens it gets.
- **Lesson:** revoke the thing the user means ("this login"), not the piece of it the client happens to hold.

## P-42 · After the blacklist app was removed, deleting a user failed

- **Session:** [036](sessions/036-login-sessions.md) (follow-up) · found by Codex's review of PR #46
- **Observed:** on a copy of the dev database (migrated on `main`, so with SimpleJWT's blacklist tables), with PR #46's
  code: deleting a user who had a row in `token_blacklist_outstandingtoken` failed with `IntegrityError: update or
  delete on table "accounts_user" violates foreign key constraint ... on table "token_blacklist_outstandingtoken"`.
  Every test passed: test databases are built fresh, without the app, so they never had those tables.
- **Root cause (Confirmed):** removing an app from `INSTALLED_APPS` doesn't touch its tables. Django deletes related
  rows itself (in Python) before deleting a user, but only for models it knows. With the app gone it didn't know
  these, and the database's foreign key refused the delete.
- **Fix:** migration `accounts/migrations/0004_drop_token_blacklist_tables.py` drops both tables if they exist and
  deletes the app's rows from `django_migrations`, so a rollback's `migrate` would build them again. Test
  `OldBlacklistTablesTests` builds the old tables with a user's row, fails on the old code (SQLite and Postgres), passes
  now; the migration was also run on a copy of the dev database with a real row.
- **Lesson:** removing an app is a migration too. Test upgrades on a database migrated by the *previous* release.

## P-43 · A tab that lost a refresh race ended the other tab's login

- **Session:** [036](sessions/036-login-sessions.md) (follow-up) · found by Codex's review of PR #46
- **Observed:** two tabs hold R0 and both need a new token. The server swaps R0 → R1 for tab A; tab B's R0 is refused
  before A has saved R1. B signed out through `logout()`, which sends `POST /auth/logout/` with R0, and since P-40 that
  ends the whole login, so A's R1 died too. Browser test: B sent the logout request (`[<Request .../auth/logout/>] != []`).
- **Root cause (Confirmed):** two things. Tabs renewed independently, so one could lose; and the automatic sign-out
  after a refused token used the same `logout()` as the button, which since P-40 ends the login for every tab.
- **Fix:** `assets/app.js`. Tabs renew one at a time under a Web Lock (`navigator.locks.request('refresh-token', …)`),
  and each first takes a newer token another tab saved (`adoptStoredToken()`). A refused token calls `signOut()`,
  which forgets the tokens in this tab only; only the button calls `logout()`. Two browser tests, both failing on the
  old code.
- **Lesson:** a fix that makes an action stronger (logout now ends *every* tab) changes every caller of it. Check who
  else calls it, and for what reason.

## P-46 · One hung refresh request stopped every tab from renewing

- **Session:** [036](sessions/036-login-sessions.md) (follow-up, round 2) · found by Codex's review of PR #46
- **Observed:** tab A sends a refresh and the answer never comes; tab B needs a new token too. B waited for the Web
  Lock for ever: its refresh was never even sent. Browser test (A's refresh route held, then the clock moved 11 s):
  `condition never became true` — B had not renewed.
- **Root cause (Confirmed, from the code and the test):** the fix for P-43 holds the `refresh-token` lock for as long
  as `spendRefreshToken()` runs, and that was `fetch(...)` followed by `res.json()` with no time limit. A browser
  waits a long time for a silent server, so one stuck request holds the lock, and with it every tab's renewal.
- **Fix:** `assets/app.js`. `postRefresh()` makes the request with an `AbortController` and aborts it after
  `REFRESH_TIMEOUT_MS` (10 s); the signal covers the body too. An abort throws `Error('refresh timed out')`, which
  callers already treat like a network error: keep the tokens, retry later, don't sign out. The lock is released when
  the function ends, in every case. One browser test, failing on the old code.
- **Lesson:** a lock held across a network call needs a time limit on the call. The lock's holder decides how long
  everyone else waits.

## P-38 · `CONN_HEALTH_CHECKS` still failed with a pool full of dead connections

- **Session:** [035](sessions/035-dead-pooled-connections.md)
- **Observed:** after `docker compose restart db`, `/readyz` answered `503 503 503` before recovering (`main`,
  `35eb53a`). The suggested fix, `CONN_HEALTH_CHECKS = True`, made a test with 3 dead connections pass after 2.9 s,
  but with 10 dead ones (a full pool) the request still failed: `couldn't get a connection after 5.00 sec`.
- **Root cause (Confirmed, from psycopg_pool's source and the timings):** a pooled connection is only found dead when
  it's used. With a check, the pool tests one connection per try and waits 0 s, ~1 s, ~2 s, ~4 s between tries; ten
  dead ones need longer than our 5 s `timeout`.
- **Fix:** our own `check` (`root/db.py`): on the first dead connection, `pool.check()` tests all idle ones at once
  and replaces the dead ones. A full pool of dead connections now recovers in ~18 ms.
- **Lesson:** test the worst case of a fix (a *full* pool), not just the case that's easy to set up.

## P-44 · One hung connection stalled every request during the pool's cleanup

- **Session:** [035](sessions/035-dead-pooled-connections.md) (follow-up) · found by Codex's review of PR #45
- **Observed:** test `test_one_hung_connection_doesnt_stall_the_others` (`root/test_database.py`): a full pool of 10
  with 5 dead connections, 1 hung (a test proxy holds the server's answers) and 4 healthy. One request, then 20 more.
  With P-38's fix: the first request **stuck** (until the test ended the hang), all **20** others failed with
  `couldn't get a connection after 5.00 sec`. Codex saw the same on a real server (one request failed after 6.4 s,
  another timed out at 5 s).
- **Root cause (Confirmed, from psycopg_pool's source and the test):** the request that met the first dead connection
  ran `pool.check()`. It takes *every* idle connection out of the pool, then tests them one by one on that request's
  thread. The hung one never answers, so the test never ends, and the pool stays empty for everyone else.
- **Fix:** `pool.drain()` instead: close every idle connection without testing it, and let the pool's background
  workers open new ones. Same test: all 21 requests succeed, the slowest in 15–27 ms (10 runs out of 10).
- **Lesson:** cleanup that does network I/O, one item after another, on a request's thread, is only as fast as the
  slowest item, and here that item could take forever. Prefer cleanup that can't wait (closing), done in the background.

## P-45 · The test proxy left 10 Postgres sessions open on Linux

- **Session:** [035](sessions/035-dead-pooled-connections.md) (follow-up)
- **Observed:** CI's `test-postgres-redis` ran all 204 tests OK, then failed: `database "test_onlinechat" is being
  accessed by other users`, `There are 10 other sessions`. On the Mac, never (also with CI's settings). In a Linux
  container (`python:3.13-slim`) running `root.test_database` and `root.test_health`: every time.
- **Root cause (Confirmed: fails on Linux, passes after the fix):** `HangingProxy` stopped by calling `close()` on
  sockets that its own threads were blocked on (`recv`, `accept`). On macOS that wakes them. On Linux it doesn't: the
  blocked call keeps the socket open, so the proxy's connections to Postgres stayed open, one session per pooled
  connection (10, a full pool).
- **Fix:** `shut()`: `shutdown(SHUT_RDWR)` before `close()`, which wakes the blocked thread and really ends the
  connection on both systems.
- **Lesson:** to stop a thread blocked on a socket, `shutdown()` it; `close()` alone is not portable. And read the exit
  code of a test run: this error comes after the `OK` line.
