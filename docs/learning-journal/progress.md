# Progress

*Updated: 2026-10-13 (session 032).*

**Status words:** **Done** = code written, tests or checks run and passing, committed.
**Partial** = some of the acceptance criteria are met. **Blocked** = waiting on something outside
our control. **Planned** = not started. Code that's written but not verified is never "Done".

## Current phase

**Stage 0: critical security and correctness fixes**, from
[docs/scaling/02-plan.md](../scaling/02-plan.md). The suggested order is in
[docs/scaling/README.md](../scaling/README.md#start-here-this-week). The
[audit's status update](../scaling/01-audit.md#status-update--2026-10-10) shows which findings
were already fixed on `main` before this journal started.

## Milestones

| Milestone | Status | Evidence | Where |
|---|---|---|---|
| Secrets/`DEBUG`/hosts from env, deps added, 48 tests + CI (work you did before this journal) | **Done** | CI on GitHub; 48 tests pass locally | `main` `763c9da`…`d00f461` (PR #5) |
| Audit, load test tooling, scaling plan | **Done** | Load test ran: 100 online healthy, 200 failed | `main` `5dabc8b` |
| Learning journal + `CLAUDE.md` | **Done**, kept up to date every task | Links checked | `main` `dff074f` and later |
| T-01 Production HTTPS settings, forged-token tests, `check --deploy` in CI | **Done**, merged as [PR #6](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/6) | 50/50 tests locally and in CI; CI security check "no issues (2 silenced)"; fails locally with a weak key | `main` `3c679a2` |
| T-08 Complete pinned deps, `pip-audit` in CI | **Done**, merged as [PR #7](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/7) | Fresh Python 3.13 venv and CI: 48/48 tests, `pip-audit` clean, Ruff clean | `main` `9b6b0fb`; CI green on the merged `main` |
| T-11 Tests + CI | **Done**, merged as [PR #14](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/14) | 53 tests; all 4 CI jobs green (lint, test, test-postgres-redis, secrets) | `t-11-tests-and-ci` |
| Branch protection (`protect-main` ruleset) | **Done** (by you) | Read back through the API: active on `main`, PR plus 4 checks plus up-to-date required | GitHub settings |
| T-02 Disconnect always marks offline (COR-2) | **Done**, merged as [PR #15](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/15) | Regression test fails before and passes after; 54/54 tests; all 4 CI jobs. Load-test acceptance not run yet | `main` `6c6e16d` |
| T-03 Throttles for login, registration, refresh, profiles, new chats (SEC-3, SEC-4) | **Done**, merged as [PR #18](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/18) | Tests failed first, then 62/62 pass; all 4 CI jobs. `NUM_PROXIES` and the load-test acceptance not done yet | `main` `f16a18b` |
| T-04 WebSocket input checks, frame limit per socket, 5 sockets per user (COR-3, SEC-5) | **Done**, merged as [PR #19](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/19) | COR-3 reproduced by a failing test, then 68/68 pass; all 4 CI jobs. DB `CHECK` and load-test acceptance not done | `main` `66060a7` |
| T-09 Gap fetch, reconnect jitter, visible close codes (COR-1, COR-4, COR-5) | **Done**, merged as [PR #20](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/20) | Tests failed first, then 73/73 pass; all 4 CI jobs. Browser check: missed messages appear after a restart; 4429 visible; refused reconnects back off | `main` `00f9789` |
| Hotfix: quiet WebSockets crashed after 5 s (redis-py 8 default timeout) | **Done**, merged as [PR #21](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/21) | Reproduced 3/3; new test failed first, passes now; full suite on real Postgres + Redis: 69 OK; all 4 CI jobs | `main` `f69fbe7` |
| Fix: leftover presence entries locked users out (one TTL per user, renewed by any tab) | **Done**, merged as [PR #22](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/22) | Tests failed first; 80/80 on real Postgres + Redis (incl. a real-Redis presence test); all 4 CI jobs; real-stack check: dead entry pruned on connect | `main` `ac84b47` |
| Baseline load test (realistic profile, second machine) | **Partial**, superseded by the rerun below | One Daphne process, `DEBUG=False`, commit `ac84b47`. Second Mac over an iPhone hotspot: 200 healthy, 300 failed, **network-limited** (P-19). Same Mac: healthy to **750**, cliff at 1,000 (WebSocket path only; REST stayed at 39 ms). Verdicts from the old tester (P-23) | [session 014](sessions/014-baseline-load-test.md) |
| Codex review #1–#2: disabled accounts refused on the socket; REST message sends limited to 60/min | **Done**, merged as [PR #25](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/25) | Socket and throttle tests failed first, then 83 OK (2 skipped); Ruff clean. all 4 CI jobs | [session 015](sessions/015-codex-review-fixes-1-2.md) |
| Codex review #3–#6: chat-switch race, "load older" order, chats after 50, lost drafts; first browser tests (Playwright) | **Done**, merged as [PR #26](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/26) | 5 of 6 browser tests failed first, then 6/6; 89 OK on real Postgres + Redis; Ruff clean. all 4 CI jobs (browser tests ran in `test-postgres-redis`). Not looked at by a person yet | [session 016](sessions/016-codex-review-frontend-fixes.md) |
| Codex review #8: load tester can say FAIL (drain, no-data = fail, recipient delivery, plan limits) | **Done**, merged as [PR #27](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/27) | Old tester: 194 sent, 0 echoes → OK; new: FAIL. Server killed mid-run: old "20/40 connected", new 0/40. 95 OK on real Postgres + Redis | [session 017](sessions/017-loadtest-verdict.md) |
| Codex audit 2 (H-05, M-21, L-01, L-02): seed can't delete real users; 0.1% errors fails; crashed reader not "online"; `make psql` uses `.env` | **Done**, merged as [PR #28](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/28) | New tests failed first (7 failures), then pass; `make test` 96 OK (6 skipped); real Postgres + Redis 102 OK; Ruff clean; real seed + load test run OK | [session 018](sessions/018-loadtest-seed-safety.md) |
| Codex audit 2 (H-02, H-03, M-17, M-18, M-19): no forged IPs (`NUM_PROXIES`), registration limit by IP even with a token, password vs name, race → 400, throttles fail open | **Done**, merged as [PR #29](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/29) | 5 of 6 new tests failed first, then pass; `make test` 102 OK (6 skipped); real Postgres + Redis 108 OK; Ruff clean; `runserver`: forged header → 429 on the 21st; Redis unreachable: old 500, new 401 | [session 019](sessions/019-account-security.md) |
| Codex audit 2 (H-01, M-01, M-02, M-05): sockets close at token expiry / disabled account / 12 h; atomic 5-socket limit (Lua); bad JSON and NUL/surrogate text get errors | **Done**, merged as [PR #30](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/30) | 7 consumer tests failed first (2 failures, 6 errors), then pass; `make test` 112 OK (8 skipped); real Postgres + Redis 118 OK; Ruff clean; real browser: closed at 18.6 s with 4401, renewed, reconnected, gap message recovered | [session 020](sessions/020-websocket-hardening.md) |
| Codex audit 2 (H-04, H-06, M-12, L-03): logout drops the old session's work; lost echo → history check; dead socket → reconnect; network errors retried, not signed out; real 429 text | **Done**, merged as [PR #31](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/31) | 10 browser tests failed first (all 10), then pass; browser suite 16 OK twice; `make test` 112 OK (9 skipped); real Postgres + Redis 128 OK; Ruff clean | [session 021](sessions/021-frontend-session-lifecycle.md) |
| Codex audit 2 (M-04, M-06, M-07, M-08): a saved message is never reported failed; reads carry `up_to`, shared by socket and REST; `peer_read_up_to` repairs lost receipts | **Done**, merged as [PR #32](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/32) | 15 new tests failed first (REST, socket, browser); browser suite 19 OK; `make test` 121 OK (10 skipped); real Postgres + Redis 140 OK; Ruff clean | [session 022](sessions/022-message-receipts.md) |
| Codex audit 2 (M-03, M-09, M-10, M-11): rows in id order; catch-up from a sync boundary on every connect; one page request at a time; history by cursor | **Done**, merged as [PR #33](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/33) | 5 new tests failed first with the audit's numbers; browser suite 23 OK; `make test` 122 OK (11 skipped); real Postgres + Redis 145 OK twice; Ruff clean | [session 023](sessions/023-message-ordering.md) |
| Codex audit 2 (M-13, M-14, M-15, M-16): the poll refreshes every loaded chat page and the open header; a blocker's photo and status hidden in the chat list; avatars ≤ 2 MiB and 4096 px; old avatar files deleted after the commit | **Done**, merged as [PR #34](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/34) | 9 new tests failed first (REST and browser), 3 guards pass; browser suite 25 OK; `make test` 132 OK (12 skipped); real Postgres + Redis 157 OK; Ruff clean | [session 024](sessions/024-privacy-and-uploads.md) |
| Codex audit 2 (M-20, M-22): the OpenAPI schema declares the JWT, real field types and real responses, with a test failing on any warning; CI fails if browser tests can't run; a failed browser start leaves nothing behind | **Done** on branch, [PR #35](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/35) open | 8 schema tests and 5 setup tests failed first, 1 guard passes; schema warnings 13 → 0; `make test` 146 OK (12 skipped); real Postgres + Redis with browser tests required 171 OK; Ruff clean | [session 025](sessions/025-api-contract-and-browser-skips.md) |
| Codex gaps at `1abe93c`: a late 401 isn't replayed for the next account; no double send during the lost-echo check; catch-up after a socket that got ready mid-history; load-test receipts carry `up_to` | **Done** on branch, PR open (stacked on #35) | 4 new tests failed first; real load test: `server_errors` 169 → 0; `make test` 147 OK (12 skipped); real Postgres + Redis with browser tests required 175 OK; Ruff clean | [session 027](sessions/027-session-replay-and-recovery.md) |
| Stage 0 baseline, rerun with the fixed tester (server Mac only; second-machine run dropped) | **Done** (docs on `t-12-stage0-baseline`) | `main` `77722d8`, one Daphne process, plan limits: **healthy at 500** (msg p95 267 ms), **fails at 750** (p95 2.3 s), 242/926 messages without echo at 1,250; chat list < 50 ms at every step | [session 028](sessions/028-stage0-baseline.md) |
| T-05 Who can start a chat: phone number required, `/users/lookup/` removed, `chat_create` 20/hour, block either way = 404 ([decision 013](decisions/013-start-a-chat-by-phone-number.md)) | **Done** on `t-05-chat-by-phone` (stacked on #38) | New tests: 8 failures + 2 errors on the old code, then pass; `make test` 152 OK (14 skipped); real Postgres + Redis with browser tests required 183 OK; Ruff clean | [session 029](sessions/029-t05-chat-by-phone.md) |
| T-07 Refresh rotation + server-side logout (SEC-7): each refresh token works once, `POST /auth/logout/` blacklists it; the browser shares one renewal per tab and picks up another tab's (same account only) ([decision 014](decisions/014-refresh-rotation-and-logout.md)) | **Done** on `t-07-refresh-rotation-logout` (stacked on #39) | 4 server tests and 3 browser tests failed first, 2 guards pass; `make test` 157 OK (15 skipped); real Postgres + Redis with browser tests required 192 OK; no missing migrations; Ruff clean | [session 030](sessions/030-t07-refresh-rotation-and-logout.md) |
| `/readyz` (T-21 part, T-12 step 3): 200 when Postgres and Redis answer, 503 naming the failed one; exempt from the HTTPS redirect | **Done** on `t-21-readyz` (stacked on #40). T-21 itself still *Partial* (outage 5xx rate not measured) | 5 tests failed first; real Daphne in production mode: 200 / 503 (Redis off) / 503 (DB off); `make test` 162 OK (15 skipped); real Postgres + Redis with browser tests required 197 OK; Ruff clean | [session 031](sessions/031-readyz.md) |
| T-13 Connection pool (psycopg 3, PERF-2): `OPTIONS['pool']` 2/10/5 s | **Done** on `t-13-db-pool` (stacked on #41) | Pool test failed first (20 connections for 20 calls); one DB call p95 7.6 → 0.67 ms; load test same Mac, same day: healthy at **500 → 2,000+** (2,000: msg p95 86 ms, p99 374 ms); Postgres sessions per run 33,566 → 227; `make test` 163 OK (16 skipped); real Postgres + Redis with browser tests required 198 OK; Ruff clean | [session 032](sessions/032-t13-connection-pool.md) |

Both PRs merged on 2026-10-10. The combined `main` passed CI (lint and tests), and 50/50 tests pass locally.

## Verified so far

| What | How | Result |
|---|---|---|
| Test suite | `make test` (`manage.py test --settings=root.settings_test`) | 175 on `fix-session-replay-and-recovery`, all pass on real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True` (no skips). Earlier: 171 on `fix-api-contract-and-browser-skips`. On SQLite: "Ran 89, OK (skipped=6)": the 2 real-Redis tests and the 4 browser test classes (a class skipped in `setUpClass` counts once) |
| Test suite on real services | CI job `test-postgres-redis` (Postgres 17, Redis 7, normal settings) | 53 pass (T-11 branch) |
| No secrets in history | CI job `secrets` (gitleaks 8.30.1, custom `django-secret-key` rule) | Clean; a planted key is caught |
| Lint | `ruff check .` (version 0.16.10, as in CI) | Clean |
| OpenAPI schema matches the API | `root/test_schema.py` (`spectacular --fail-on-warn --validate`, plus 7 contract checks) | 0 warnings, 0 errors (was 13 warnings) |
| No model changes missing a migration | `makemigrations --check --dry-run --settings=root.settings_test` | No changes |
| Tokens signed with another key are rejected | `SigningKeyTests` | Pass |
| Production security settings | `check --deploy --tag security --fail-level WARNING` with production env | Passes; W005/W021 silenced deliberately |
| Fresh install works | New Python 3.13 venv + `pip install -r requirements.txt`; your `.venv` synced too | Tests pass, psycopg 3 in use |
| No known vulnerable versions | `pip-audit -r requirements.txt` | None found (2026-10-10) |

## Known issues (open)

See the [audit](../scaling/01-audit.md) and its status update. The most important still-open items:
- SEC-3/4/5 and COR-3 fixed (T-03, T-04, merged). COR-1/4/5 fixed on the T-09 branch, checked in a browser. The redis-py 8 regression (quiet sockets crash) is fixed in PR #21.
- **Codex audit 2** ([checklist](../scaling/05-codex-audit-2026-10-11.md)): 31 findings + 7 risks; 4 fixed in session 018, 5 in 019, 4 in 020, 4 in 021, 4 in 022, 4 in 023, 4 in 024, 2 in 025: all 31 findings fixed. Left: the risks R-01…R-07. Four later Codex gaps fixed in session 027.
- **Load-test verdict ignores `server_errors`** (session 027): 169 error frames still gave OK. The load-tester tests also skip in CI (no `aiohttp` there). The reverse proxy must cap request bodies (session 024). The load tester should reconnect at token expiry now that browsers do (decision 006).
- **Codex review #9** (REST read receipts) fixed in session 022 (M-07). #7 (24 h group expiry) fixed in session 020 (M-02). #8 (load tester) fixed in session 017; the baseline was rerun in session 028 (healthy at 500, failing at 750).
- **PERF-1/2/3:** one DB thread per process (open), a new DB connection per call (**fixed by T-13**, session 032), seven DB trips per message (T-15, open).
- Dependabot backlog cleared: #8–#11 merged; #12 and #13 replaced by #16 ([P-14](problems-and-solutions.md#p-14--dependabot-prs-that-could-never-be-merged)).
  Auto-merge is on: for new Dependabot PRs, comment `@dependabot rebase`, then enable auto-merge.

## PR #34 follow-ups (session 026)

**Done on `fix-pr34-followups`:** profile PATCH reloads and locks the row, saves only submitted fields,
cleanup failures are logged, chat refresh merges ids, refreshes lookup-opened chats and survives vanished pages.
Six regressions were reproduced on the old code. PostgreSQL/Redis: 166 tests OK (one optional load-test
skip, subsequently run successfully); four final API guards plus that optional test: 5 OK. SQLite:
139 tests OK (14 skips). Ruff, JavaScript syntax and
migration checks pass. See [session 026](sessions/026-pr34-followups.md) for exact results and limitations.

## Documentation backlog

- None outstanding. Session 001 was written after the fact (see its note). Sessions 003 and 004
  describe the first versions of T-01 and T-08; session 006 explains how they were redone.

---

## Learning tracker

**Levels:** Introduced → Explained → Practiced → Demonstrated (definitions in the
[README](README.md#how-to-use-it-to-learn)). **Unknown** = no evidence either way.

**Baseline (2026-10-10):** you described yourself as a junior Python backend developer who
knows Python and basic Django, and the basics of WebSockets and scaling, but not this level.
That's self-reported; nothing has been tested yet, so every concept starts at
*Explained* with your own level *Unknown*.

| Concept | Guide | Status | Evidence | Exercise to reach "Practiced" |
|---|---|---|---|---|
| HTTP vs WebSocket | [guide](concepts/http-and-websockets.md) | Explained | Sessions 001, 005 | Open the app, then the browser DevTools → Network → WS. Watch frames as you send a message. Write down every frame type you see. |
| Channels, consumers, groups, Redis channel layer | [guide](concepts/django-channels-and-redis.md) | Explained | Session 001 | Without looking, draw the path of one message from browser A to browser B, naming the functions in `chats/consumers.py`. |
| JWT and signing | [guide](concepts/authentication-and-jwt.md) | Explained | Session 003 | Paste an access token into a JWT decoder (offline tool or `python -c`). Explain each claim. Then change one character of the signature and explain why the server rejects it. |
| Configuration, secrets, DEBUG, HTTPS settings | [guide](concepts/configuration-and-secrets.md) | Explained | Session 003 | Start the server with `DJANGO_DEBUG=0` and no `DJANGO_ALLOWED_HOSTS`. Predict the error first, then check. |
| Dependency management | [guide](concepts/dependency-management.md) | Explained | Session 004 | Add a package to `requirements.in`, run `pip-compile`, and read the diff. Revert afterwards. |
| Git branches, merge, rebase | [guide](concepts/git-branches-merge-rebase.md) | Explained | Sessions 002, 003 | In a throwaway repo, make a fast-forward merge, a rebase and a `--force-with-lease` push to a local bare remote. |
| Performance, bottlenecks, load testing | [guide](concepts/performance-and-load-testing.md) | Explained | Session 001 | Recompute the PERF-4 table yourself for 150 users. Predict healthy or failing. |
| Rate limiting (throttles) | [guide](concepts/rate-limiting.md) | Explained | Session 009 | Run the server, then send 6 wrong logins for one number with `curl` in a loop. Read the 429 and its `Retry-After` header. Predict when the 7th will work, then check. |
| Reliable delivery, cursors, jitter | [guide](concepts/reliable-delivery-and-reconnects.md) | Explained | Session 011 | With the app running, open a chat, stop the server for 10 s, send a message from the other account over REST, start the server. Predict what the chat shows, then watch DevTools → Network for the `?after=` request. |
| Testing, CI, test databases, secret scanning | [guide](concepts/testing-and-ci.md) | Explained | Session 007 | Break a test on purpose (change an expected status code), push to a PR branch, and read the CI log to find it. Then explain P-12 in your own words. |
| File uploads, storage, signals, `on_commit` | [guide](concepts/file-uploads-and-storage.md) | Explained | Session 024 | Upload a photo in the app, then replace it. Before you look, predict what `ls media/avatars` shows; then check. Then upload a 3 MB photo and read the 400. |
| API contracts, OpenAPI, drf-spectacular | [guide](concepts/api-contracts-and-openapi.md) | Explained | Session 025 | Open `/api/schema/swagger-ui/`, press Authorize, paste an access token, and call `GET /api/v1/chats/`. Then remove `-> bool` from `get_is_online`, predict which test fails, run `make test`, and put it back. |
| Health checks: liveness vs readiness | [guide](concepts/health-checks.md) | Explained | Session 031 | Start the app (`make up`, then `daphne -p 8002 root.asgi:application`), `curl -i localhost:8002/readyz`. Predict the answer with `REDIS_PORT=6390`, then check. Then explain why a 503 shouldn't restart the process. |

Mark a row *Practiced* yourself after doing its exercise. It becomes *Demonstrated* when you
explain or apply the concept without help, for example by answering a session's review
questions out loud or fixing a related bug yourself.
