# Testing and CI

**Prerequisites:** [Django Channels and Redis](django-channels-and-redis.md), [Configuration and secrets](configuration-and-secrets.md).

## 1. Simple definition
- An **automated test** is code that runs your code and checks the result.
- **CI (Continuous Integration)** is a server that runs all those tests, plus linters and scanners,
  on every change, before the change is merged.
- **Branch protection** makes CI mandatory: GitHub refuses to merge until the checks pass.

## 2. Why it exists
- Without tests, every change is a guess, and every bug is found by users.
- Without CI, tests only run when someone remembers to run them, on their own machine, with their own setup.
- CI gives every change the same clean, repeatable check, and branch protection makes sure nobody can skip it.

## 3. How it works here, step by step
1. You push a branch and open a PR.
2. GitHub Actions reads `.github/workflows/tests.yml` and starts **four jobs in parallel**, each on a
   fresh Ubuntu machine:

   | Job | What it proves |
   |---|---|
   | `lint` | Ruff finds no likely bugs or style errors |
   | `test` | The deps have no known vulnerabilities (`pip-audit`); 53 tests pass on SQLite; no missing migrations; the production settings pass `check --deploy` |
   | `test-postgres-redis` | The same tests pass against **real** Postgres 17 and Redis 7, with the normal settings |
   | `secrets` | No secret is anywhere in the git history (gitleaks) |

3. The `protect-main` ruleset only allows the merge when all four are green **and** the branch is up
   to date with `main`.

## 4. Small example: what a Django test looks like
```python
class LoginTests(TestCase):
    def test_wrong_password_is_refused(self):
        response = APIClient().post('/api/v1/auth/login/', {'phone_number': phone(1), 'password': 'nope'})
        self.assertEqual(response.status_code, 401)
```
Arrange (a user exists, from `setUp`), act (post the wrong password), assert (401). Name each test after
the behaviour it protects, so a failure reads like a sentence.

## 5. In our project

### Two kinds of test database
- **Fast:** `root/settings_test.py` swaps in SQLite in memory, an in-memory channel layer, a local-memory
  cache and fast password hashing. The whole suite runs in under a second, with no services needed. Use `make test`.
- **Realistic:** the `test-postgres-redis` CI job uses the normal `root/settings.py` against real services.
  It's slower (about 1.5 minutes) but behaves like production.
- **Why both:** the fast one is for you, many times an hour. The realistic one catches what the fast one hides.
  On its first run it found that every WebSocket test was broken on Postgres
  ([P-12](../problems-and-solutions.md#p-12--websocket-tests-passed-on-sqlite-but-failed-on-postgres)).

### `TestCase` vs `TransactionTestCase`
| | `TestCase` | `TransactionTestCase` |
|---|---|---|
| How it isolates tests | Wraps each test in a transaction and rolls it back | Really commits, then empties every table after the test |
| Speed | Fast | Slower |
| Use when | Normal views and models | Code that manages connections or transactions itself, e.g. Channels consumers via `database_sync_to_async` |

### Secret scanning (gitleaks)
- `gitleaks git .` reads every commit and matches the content against rules for known secret formats.
- `.gitleaks.toml` adds our own rule for hard-coded Django keys (regex `SECRET_KEY\s*=\s*['"]…['"]`),
  because the built-in rules missed the real one ([P-11](../problems-and-solutions.md#p-11--gitleaks-built-in-rules-missed-our-real-leaked-key)).
- `.gitleaksignore` lists leaks that are known **and already revoked**. Each line is a fingerprint:
  `commit:file:rule:line`.

### Mocks and fakes
`test_helpers.FakePresenceMixin` replaces the Redis presence client with a dictionary for each test. Fakes
make tests fast and independent, but they can drift from the real thing. The real-services job is the safety net.

## 6. Alternatives
- **pytest + pytest-django** instead of Django's runner: shorter tests and fixtures, very popular. Django's
  runner is fine here, and switching would be a big diff for little gain.
- **Testcontainers:** start a real Postgres from inside the tests. That's useful locally when Docker is available.
- **Other CI systems** (GitLab CI, CircleCI): same idea, different config file.
- **Other secret scanners** (trufflehog, GitHub's built-in secret scanning): run more than one if secrets are critical.

## 7. Common mistakes
- **Trusting a green check without knowing what it tests.** CI was green on SQLite while the WebSocket tests
  were broken on Postgres.
- **Trusting a "clean" scan.** Test the scanner on a planted secret first.
- **Using `TestCase` for code that closes or manages connections**, like Channels consumers.
- **Testing only the happy path.** Our refresh tests also check that garbage and *access* tokens are refused.
- **Allowing merges without required checks.** Then CI is only advice.

## 8. When to use it
Always, for anything you'll keep. Write the test that reproduces a bug *before* fixing it, so you know the fix works.
