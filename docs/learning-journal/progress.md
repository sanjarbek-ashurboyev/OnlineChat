# Progress

*Updated: 2026-10-11 (session 022).*

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
| Baseline load test (realistic profile, second machine) | **Partial** | One Daphne process, `DEBUG=False`, commit `ac84b47`. Second Mac over an iPhone hotspot: 200 healthy, 300 failed, **network-limited** (P-19). Same Mac: healthy to **750**, cliff at 1,000 (WebSocket path only; REST stayed at 39 ms). **Verdicts unconfirmed:** measured with the old tester (P-23); rerun pending | [session 014](sessions/014-baseline-load-test.md) |
| Codex review #1–#2: disabled accounts refused on the socket; REST message sends limited to 60/min | **Done**, merged as [PR #25](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/25) | Socket and throttle tests failed first, then 83 OK (2 skipped); Ruff clean. all 4 CI jobs | [session 015](sessions/015-codex-review-fixes-1-2.md) |
| Codex review #3–#6: chat-switch race, "load older" order, chats after 50, lost drafts; first browser tests (Playwright) | **Done**, merged as [PR #26](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/26) | 5 of 6 browser tests failed first, then 6/6; 89 OK on real Postgres + Redis; Ruff clean. all 4 CI jobs (browser tests ran in `test-postgres-redis`). Not looked at by a person yet | [session 016](sessions/016-codex-review-frontend-fixes.md) |
| Codex review #8: load tester can say FAIL (drain, no-data = fail, recipient delivery, plan limits) | **Done**, merged as [PR #27](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/27) | Old tester: 194 sent, 0 echoes → OK; new: FAIL. Server killed mid-run: old "20/40 connected", new 0/40. 95 OK on real Postgres + Redis | [session 017](sessions/017-loadtest-verdict.md) |
| Codex audit 2 (H-05, M-21, L-01, L-02): seed can't delete real users; 0.1% errors fails; crashed reader not "online"; `make psql` uses `.env` | **Done**, merged as [PR #28](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/28) | New tests failed first (7 failures), then pass; `make test` 96 OK (6 skipped); real Postgres + Redis 102 OK; Ruff clean; real seed + load test run OK | [session 018](sessions/018-loadtest-seed-safety.md) |
| Codex audit 2 (H-02, H-03, M-17, M-18, M-19): no forged IPs (`NUM_PROXIES`), registration limit by IP even with a token, password vs name, race → 400, throttles fail open | **Done**, merged as [PR #29](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/29) | 5 of 6 new tests failed first, then pass; `make test` 102 OK (6 skipped); real Postgres + Redis 108 OK; Ruff clean; `runserver`: forged header → 429 on the 21st; Redis unreachable: old 500, new 401 | [session 019](sessions/019-account-security.md) |
| Codex audit 2 (H-01, M-01, M-02, M-05): sockets close at token expiry / disabled account / 12 h; atomic 5-socket limit (Lua); bad JSON and NUL/surrogate text get errors | **Done**, merged as [PR #30](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/30) | 7 consumer tests failed first (2 failures, 6 errors), then pass; `make test` 112 OK (8 skipped); real Postgres + Redis 118 OK; Ruff clean; real browser: closed at 18.6 s with 4401, renewed, reconnected, gap message recovered | [session 020](sessions/020-websocket-hardening.md) |
| Codex audit 2 (H-04, H-06, M-12, L-03): logout drops the old session's work; lost echo → history check; dead socket → reconnect; network errors retried, not signed out; real 429 text | **Done**, merged as [PR #31](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/31) | 10 browser tests failed first (all 10), then pass; browser suite 16 OK twice; `make test` 112 OK (9 skipped); real Postgres + Redis 128 OK; Ruff clean | [session 021](sessions/021-frontend-session-lifecycle.md) |
| Codex audit 2 (M-04, M-06, M-07, M-08): a saved message is never reported failed; reads carry `up_to`, shared by socket and REST; `peer_read_up_to` repairs lost receipts | **Done** on branch, PR open | 15 new tests failed first (REST, socket, browser); browser suite 19 OK; `make test` 121 OK (10 skipped); real Postgres + Redis 140 OK; Ruff clean | [session 022](sessions/022-message-receipts.md) |

Both PRs merged on 2026-10-10. The combined `main` passed CI (lint and tests), and 50/50 tests pass locally.

## Verified so far

| What | How | Result |
|---|---|---|
| Test suite | `make test` (`manage.py test --settings=root.settings_test`) | 140 on `fix-message-receipts`, all pass on real Postgres + Redis. Earlier: 128 on `fix-frontend-session-lifecycle`. On SQLite: "Ran 89, OK (skipped=6)": the 2 real-Redis tests and the 4 browser test classes (a class skipped in `setUpClass` counts once) |
| Test suite on real services | CI job `test-postgres-redis` (Postgres 17, Redis 7, normal settings) | 53 pass (T-11 branch) |
| No secrets in history | CI job `secrets` (gitleaks 8.30.1, custom `django-secret-key` rule) | Clean; a planted key is caught |
| Lint | `ruff check .` (version 0.16.10, as in CI) | Clean |
| No model changes missing a migration | `makemigrations --check --dry-run --settings=root.settings_test` | No changes |
| Tokens signed with another key are rejected | `SigningKeyTests` | Pass |
| Production security settings | `check --deploy --tag security --fail-level WARNING` with production env | Passes; W005/W021 silenced deliberately |
| Fresh install works | New Python 3.13 venv + `pip install -r requirements.txt`; your `.venv` synced too | Tests pass, psycopg 3 in use |
| No known vulnerable versions | `pip-audit -r requirements.txt` | None found (2026-10-10) |

## Known issues (open)

See the [audit](../scaling/01-audit.md) and its status update. The most important still-open items:
- SEC-3/4/5 and COR-3 fixed (T-03, T-04, merged). COR-1/4/5 fixed on the T-09 branch, checked in a browser. The redis-py 8 regression (quiet sockets crash) is fixed in PR #21.
- **Codex audit 2** ([checklist](../scaling/05-codex-audit-2026-10-11.md)): 31 findings + 7 risks; 4 fixed in session 018, 5 in 019, 4 in 020, 4 in 021, 4 in 022. Next: ordering and paging (M-03, M-09, M-10, M-11). The load tester should reconnect at token expiry now that browsers do (decision 006).
- **Codex review #9** (REST read receipts) fixed in session 022 (M-07). #7 (24 h group expiry) fixed in session 020 (M-02). #8 (load tester) fixed in session 017; the baseline rerun is pending. Session 014's capacity numbers need a rerun after #8.
- **PERF-1/2/3:** one DB thread per process, plus a new DB connection per call (Stage 1).
- Dependabot backlog cleared: #8–#11 merged; #12 and #13 replaced by #16 ([P-14](problems-and-solutions.md#p-14--dependabot-prs-that-could-never-be-merged)).
  Auto-merge is on: for new Dependabot PRs, comment `@dependabot rebase`, then enable auto-merge.

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

Mark a row *Practiced* yourself after doing its exercise. It becomes *Demonstrated* when you
explain or apply the concept without help, for example by answering a session's review
questions out loud or fixing a related bug yourself.
