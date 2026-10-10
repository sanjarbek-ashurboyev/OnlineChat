# Progress

*Updated: 2026-10-10 (session 010).*

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
| T-04 WebSocket input checks, frame limit per socket, 5 sockets per user (COR-3, SEC-5) | **Done** locally, PR open | COR-3 reproduced by a failing test, then 68/68 pass; Ruff clean. DB `CHECK` and load-test acceptance not done | `t-04-ws-input-validation` |
| T-09 Gap fetch + reconnect jitter | Planned | | |
| Hotfix: quiet WebSockets crashed after 5 s (redis-py 8 default timeout) | **Done** locally, PR open | Reproduced 3/3; new test failed first, passes now; full suite on real Postgres + Redis: 69 OK | `fix-redis-socket-timeout` |
| Baseline load test (realistic profile, second machine) | Planned | | |

Both PRs merged on 2026-10-10. The combined `main` passed CI (lint and tests), and 50/50 tests pass locally.

## Verified so far

| What | How | Result |
|---|---|---|
| Test suite | `make test` (`manage.py test --settings=root.settings_test`) | 68 on the T-04 branch, all pass |
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
- SEC-3/4 fixed by T-03 (merged). SEC-5 and COR-3 fixed on the T-04 branch (frame limit, type checks, socket cap).
- **COR-1:** messages that arrive during a reconnect never show in the open chat (T-09).
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
| Testing, CI, test databases, secret scanning | [guide](concepts/testing-and-ci.md) | Explained | Session 007 | Break a test on purpose (change an expected status code), push to a PR branch, and read the CI log to find it. Then explain P-12 in your own words. |

Mark a row *Practiced* yourself after doing its exercise. It becomes *Demonstrated* when you
explain or apply the concept without help, for example by answering a session's review
questions out loud or fixing a related bug yourself.
