# 007 · T-11: tests and CI against real services, secret scanning, branch protection

- **Date:** 2026-10-10 · **Phase:** Stage 0
- **Task:** T-11 (fixes the rest of OPS-1/OPS-2) · **PR:** [#14](https://github.com/sanjarbek-ashurboyev/OnlineChat/pull/14), branch `t-11-tests-and-ci`
- **Files:**
  - `accounts/tests.py`, `chats/test_consumers.py`
  - `.github/workflows/tests.yml`, `.github/dependabot.yml`
  - `.gitleaks.toml`, `.gitleaksignore` (new)
  - docs
- **Objective:** finish what PR #5 started: test the refresh flow, run CI against the real services, scan for secrets.

## What we accomplished
- **Cleanup:** deleted the merged and stale branches (`t-01-…`, `t-08-…`, `loadtest-and-scaling-docs`),
  locally and on GitHub, after checking that their content was on `main`.
- **3 refresh-token tests:**
  - a refresh token yields an access token that works;
  - a garbage refresh token gets 401;
  - an **access** token can't be used as a refresh token.
- **CI job `test-postgres-redis`:** the suite with the normal settings against Postgres 17 + Redis 7.
  - Its first run **failed**: 13 WebSocket tests errored on Postgres ([P-12](../problems-and-solutions.md#p-12--websocket-tests-passed-on-sqlite-but-failed-on-postgres)).
  - Fixed by switching the WebSocket tests to `TransactionTestCase`.
- **CI job `secrets`:** gitleaks 8.30.1, downloaded and checked against its SHA-256.
  - The built-in rules **missed** our real leaked key ([P-11](../problems-and-solutions.md#p-11--gitleaks-built-in-rules-missed-our-real-leaked-key)),
    so we added a custom rule, an allowlist for the dev fallback, and an ignore entry for the burned key.
- **Confirmed P-04:** a Homebrew Postgres 14 owns port 5432.
- **Decided:** a pull request for every change, docs included. **You** created the `protect-main` ruleset
  on GitHub. Claude checked it through the API: active, PR required, 4 required checks, branch must be up to date.
- **Fixed duplicate Dependabot PRs** (#12 and #13 both bump aiohttp). The root entry already covers `loadtest/`,
  so the separate `/loadtest` entry was removed.

**Results** (all actually run):

| Check | Result |
|---|---|
| `make test` locally (SQLite) | 53/53 OK |
| CI `test-postgres-redis` | First run 13 errors; after the fix, pass |
| CI `lint`, `test`, `secrets` | Pass |
| gitleaks on this repo / on a planted key | Clean / "leaks found: 1" |

**Not done:**
- The Postgres/Redis job wasn't run locally: Docker wasn't running, and the local Postgres is 14, too old.
- The Dependabot PRs still need handling after #14 merges (see [progress](../progress.md)).

## Concepts I learned
- **Fast vs realistic test databases, `TestCase` vs `TransactionTestCase`, secret scanning, branch protection:**
  [testing-and-ci](../concepts/testing-and-ci.md) (new).
- **Why access tokens must not refresh:** [authentication-and-jwt](../concepts/authentication-and-jwt.md).
  Access tokens are short-lived on purpose; letting them refresh would make them effectively permanent.

## Important code walkthrough

### The test that guards the token types (`accounts/tests.py`)
```python
def test_an_access_token_cannot_be_used_to_refresh(self):
    # Otherwise a short-lived access token could be renewed forever.
    response = APIClient().post(self.REFRESH_URL, {'refresh': token_for(self.user)})
    self.assertEqual(response.status_code, 401)
```
`token_for()` makes an **access** token. SimpleJWT's refresh serializer checks the token's `token_type`
claim and rejects it. We didn't write that check, but the test makes sure a future setting or library
change can't silently remove it.

### The one-line fix with the long explanation (`chats/test_consumers.py`)
```python
# TransactionTestCase, not TestCase: database_sync_to_async closes any connection
# whose autocommit is off, and TestCase's per-test transaction turns it off. On
# PostgreSQL that kills the test's own connection; in-memory SQLite ignores close().
class InboxSocketTestCase(FakePresenceMixin, TransactionTestCase):
```
The comment matters more than the code. Without it, someone "optimises" this back to `TestCase` because
it's faster, and the tests pass locally on SQLite.

### The CI job for real services (`.github/workflows/tests.yml`)
```yaml
test-postgres-redis:
  services:
    postgres: { image: postgres:17-alpine, ... }   # same versions as compose.yaml
    redis:    { image: redis:7-alpine, ... }
  env:
    DJANGO_SSL_REDIRECT: "False"   # DEBUG is off; the test client speaks plain HTTP
  steps: ... python manage.py test   # normal settings, not settings_test
```
**Services** are containers GitHub starts next to the job, reachable on `localhost`. The health-check
options make the job wait until Postgres and Redis actually answer.

### Secret scanning config
- **`.gitleaks.toml`:** `[extend] useDefault = true` keeps all the built-in rules and adds ours. The
  `[[rules.allowlists]]` entry exempts one exact value, the dev fallback, so it still works when lines move.
- **`.gitleaksignore`:** one fingerprint, `3bd73a8…:root/settings.py:django-secret-key:13`. That's precise:
  the same key anywhere *else* would still be reported.

## Problems we encountered
- [P-12 · WebSocket tests passed on SQLite but failed on Postgres](../problems-and-solutions.md#p-12--websocket-tests-passed-on-sqlite-but-failed-on-postgres).
  **How it was diagnosed:**
  1. Saved the failed CI log with `gh run view --log-failed`.
  2. Noticed only WebSocket tests failed, all with the same error, at the consumer's database calls.
  3. Read `channels/db.py` and Django's `close_if_unusable_or_obsolete()`.
  4. Noticed SQLite's `close()` is a no-op for in-memory databases.
- [P-11 · gitleaks' built-in rules missed our real leaked key](../problems-and-solutions.md#p-11--gitleaks-built-in-rules-missed-our-real-leaked-key)
- [P-04 confirmed: Homebrew Postgres 14 on port 5432](../problems-and-solutions.md#p-04--makemigrations---check-warned-it-couldnt-connect-to-postgres)

## Engineering decisions and trade-offs
- **Keep the fast SQLite job *and* add a real-services job,** instead of replacing it. Fast feedback locally,
  realistic checks in CI. The cost: about 1.5 minutes per PR.
- **Download gitleaks with a checksum** instead of a third-party GitHub Action. It's transparent, pinned, and
  needs no extra permissions or licence.
- **A custom rule plus a fingerprint ignore,** not "turn the rule off". The burned key is accepted *by
  fingerprint*, and anything new still fails.
- **PRs for everything, enforced by a ruleset** ([decision 003](../decisions/003-one-branch-per-task.md)).
  **You** created the ruleset, because it limits the AI too.

## What I should remember
- A test environment that differs from production can hide broken tests. Run at least one job on the real thing.
- `TestCase` for normal code; `TransactionTestCase` when the code under test manages connections (Channels).
- "No leaks found" means "nothing matched". Prove the scanner works on a planted example.
- A required check that doesn't exist on an old PR blocks it forever: update the PR so the check runs.
- Read CI logs from the bottom up: find the *first* real error, then group failures by what they have in common.

## Review questions
1. Why did the WebSocket tests pass on SQLite but fail on Postgres? Explain in three steps.
2. Would `TestCase` → `TransactionTestCase` be the right fix if the REST tests had failed the same way? Why or why not?
3. Debugging: a new test fails only in `test-postgres-redis` with `duplicate key value violates unique constraint`. What might SQLite have been hiding, and how would you investigate?
4. Why does `.gitleaksignore` use a fingerprint (commit:file:rule:line) instead of ignoring `root/settings.py`?
5. The Dependabot PRs show "Expected — waiting for status" for `secrets`. Why, and what fixes it?
6. Design: why keep the fast SQLite test job at all, now that we have the realistic one?

<details><summary>Answer key</summary>

1. (1) `TestCase` runs each test in a transaction, so autocommit is off. (2) Channels' `database_sync_to_async`
   calls `close_old_connections()`, which closes connections whose autocommit differs from the setting, so the
   test's connection and transaction are gone. (3) SQLite in memory ignores `close()`, so nothing broke there.
2. Probably not. REST views don't call `close_old_connections()` inside the test, so the cause would be
   different. Diagnose first; don't reuse a fix because the symptom looks similar.
3. SQLite is looser with some constraints and types, and test data may collide differently. Read the full error
   (which constraint, which values), reproduce against Postgres locally (Docker), and check whether the test
   relies on specific ids, or on `TransactionTestCase` not resetting sequences.
4. So only that exact, already-revoked occurrence is accepted. A new secret in the same file, or the same
   key leaked again elsewhere, is still reported.
5. Their branches were created before the job existed, so it never runs there. Update the branch from `main`
   (`@dependabot rebase`), and CI runs all four jobs.
6. Speed. Under a second locally with no services, versus about 1.5 minutes in CI. Fast feedback while coding,
   realistic proof before merging.
</details>

## Next steps
- Merge PR #14 (once it's marked ready). Then handle the Dependabot PRs in the order in [progress](../progress.md).
- Optional: start Docker Desktop and stop the Homebrew Postgres (`brew services stop postgresql@14`),
  so `make up` works locally (T-10).
- Next tasks: **T-02** (disconnect always marks offline) → **T-03/T-04** (rate limits, COR-3).
- Review beforehand: [testing-and-ci](../concepts/testing-and-ci.md), sections 5 and 7.
