# 006 · Syncing with GitHub, and redoing T-01 and T-08 on the real `main`

- **Date:** 2026-10-10 · **Phase:** Stage 0
- **Tasks:** T-01, T-08 (redone), T-11 (status re-checked)
- **Commits:**
  - `main`: `5dabc8b` docs, `dff074f` journal, `05ec1f9` Ruff fix, then this docs update.
  - `t-01-settings-from-env`: `9d3ef86`.
  - `t-08-pinned-deps`: `ec6f48e`.
- **Objective:** push everything to GitHub, which turned into "find out why we can't, and fix it without losing anyone's work".

## What we accomplished
1. **Gave Claude permission to push.** You added two rules to `.claude/settings.local.json`. That
   file is ignored by your global git ignore, so it's never committed.
2. **Pointed `origin` at the moved repository**, ran `git fetch`, and found GitHub's `main` **5
   commits ahead** of ours ([P-09](../problems-and-solutions.md#p-09--local-main-was-five-commits-behind-github)).
   Those commits, from 2026-10-06 to 10-08 and including PR #5, had already done:
   - secrets, `DEBUG` and hosts from env;
   - the missing dependencies, with SimpleJWT pinned;
   - 48 tests and CI (Ruff, tests on SQLite, `makemigrations --check`);
   - the message length cap;
   - the avatars removed from git.
3. **Stopped before pushing.** A plain push would have been rejected; a forced one would have
   deleted that work. You approved a plan to rebuild on top of it.
4. **Rebased our 2 `main` commits** (docs, journal) onto `origin/main`. Only `.gitignore` conflicted;
   both sides' lines were kept.
5. **Ran CI's checks locally before pushing:**
   - the tests passed;
   - Ruff found one issue in our `loadtest_seed.py` (`zip()` without `strict=`), fixed in `05ec1f9`.
   - Then `main` was pushed as a **normal fast-forward**.
6. **Rebuilt T-01 as an addition, not a replacement:**
   - kept their `DJANGO_DEBUG=True/False` convention and their dev-only fallback key;
   - added `CSRF_TRUSTED_ORIGINS`, the `if not DEBUG:` HTTPS block, the forged-token tests, and a CI
     step running `check --deploy --tag security --fail-level WARNING`;
   - changed your local `.env` from `DJANGO_DEBUG=1` to `DJANGO_DEBUG=True`;
   - pushed with `--force-with-lease=t-01-settings-from-env:68468d0`.
7. **Rebuilt T-08 the same way:**
   - `requirements.in`, compiled with **Python 3.13** to match CI (45 pins);
   - `pip-audit` in CI, and Dependabot (pip and GitHub Actions);
   - pushed as a new branch.
8. **Re-checked the audit** against the new code and added a status update to `docs/scaling/01-audit.md`,
   `03-operations.md` and `README.md`. Updated this journal so it no longer describes old code.

**Results** (all actually run):

| Check | Result |
|---|---|
| `main` tests | 48/48 OK |
| T-01 branch tests | 50/50 OK. They were 29 failures and 10 errors before the test-settings fix ([P-10](../problems-and-solutions.md#p-10--39-tests-failed-after-adding-the-https-settings)). |
| T-01 deploy check | Passes with a strong key ("2 silenced"); fails with a weak key (W009) |
| T-08 fresh Python 3.13 venv | 48/48 OK, psycopg 3, no missing migrations, `pip-audit` clean |
| `ruff check .` on all three | Clean |

**Not done:** the PRs for T-01 and T-08 aren't opened yet, and CI hasn't run on GitHub yet; only locally.

## Concepts I learned
- **`git fetch`, ahead/behind, and why your local view can be stale:** [git guide](../concepts/git-branches-merge-rebase.md)
- **Test settings that inherit production settings:** [configuration guide](../concepts/configuration-and-secrets.md)
- **pip-compile keeps existing pins:** [dependency guide](../concepts/dependency-management.md)

### New idea: "local" vs "remote" state in git
- **Simple definition:** your repository has *your* branches (`main`) and *remembered copies* of
  GitHub's (`origin/main`). The remembered copies only update when you `git fetch` or `git pull`.
- **Why it matters:** `git status` said "nothing to commit" the whole time, and that was true about
  your files. It said nothing about GitHub, because git hadn't asked GitHub in days.
- **How to check:** `git fetch`, then `git status -sb` shows `## main...origin/main [ahead 2, behind 5]`.
  - *Ahead* = commits you have that GitHub doesn't.
  - *Behind* = the reverse.
  - Both at once = **diverged**: you must rebase or merge before pushing.
- **Common mistake:** "fixing" a rejected push with a forced push. That deletes the remote's extra commits.

### New idea: build on existing work instead of replacing it
Our first T-01 replaced `settings.py` lines wholesale. The second time, the same goal was reached by
**adding** only what was missing, in the existing style (`== 'True'`, not `== '1'`). Smaller diffs
are easier to review, and they don't throw away someone else's decisions. That's the "surgical
changes" rule in `CLAUDE.md`.

## Important code walkthrough

### The CI security check (T-01 branch, `.github/workflows/tests.yml`)
```yaml
- name: Production settings pass Django's security checks
  env:
    DJANGO_DEBUG: "False"
    DJANGO_SECRET_KEY: ci-only-${{ github.run_id }}-not-a-real-secret-but-long-enough-for-w009
    ...
  run: python manage.py check --deploy --tag security --fail-level WARNING
```
- **`--deploy`** adds the production checks. **`--tag security`** limits the run to security checks,
  so drf-spectacular's schema warnings don't count.
- **`--fail-level WARNING`** makes any warning fail the build. Normally only errors do.
- **The key** is fake but long and varied, because W009 rejects short or `django-insecure-` keys. It's
  safe to have in the file because it protects nothing.
- **Why W005/W021 are silenced in `settings.py`:** HSTS for subdomains and for the preload list are
  deliberate opt-ins. Silencing them, with a comment, records that decision, and any *new* security
  warning still fails CI.

### Why test settings needed a change (`root/settings_test.py`)
```python
# DEBUG is off here, so production's HTTPS redirect is on; the test client speaks plain HTTP.
SECURE_SSL_REDIRECT = False
```
`settings_test.py` does `from root.settings import *`, so it inherits **everything**, including the
new production block. One line turns off the single setting that breaks the test client.

## Problems we encountered
- [P-09 · Local `main` was five commits behind GitHub](../problems-and-solutions.md#p-09--local-main-was-five-commits-behind-github)
- [P-10 · 39 tests failed after adding the HTTPS settings](../problems-and-solutions.md#p-10--39-tests-failed-after-adding-the-https-settings)
- **Ruff's B905 on `zip()` in our seed script.** It was caught by running CI's linter locally before pushing.
- **A wrong explanation, corrected.** I first said the `redis` pin changed from 8.1.0 to 7.4.1
  "because we compiled for Python 3.13". A test proved that wrong: compiling for 3.13 into an
  **empty** file gives `redis==8.1.0` and `Django==6.1.2`. The real cause is that **pip-compile keeps
  the pins already in `requirements.txt`** when they still fit, and `main`'s file had `redis==7.4.1`
  and `Django==6.1.1`. To move to the newest versions, run `pip-compile --upgrade` (or let Dependabot do it).

## Engineering decisions and trade-offs
- **Keep their convention (`True`) over ours (`1`).** Consistency with existing code and docs beats
  personal preference. The cost: your `.env` had to change.
- **Keep the dev-only fallback key.** It's safe because it only exists when DEBUG is on. It also lowers
  the setup effort for new developers.
- **Compile pins for 3.13, the version CI uses.** CI is the reference environment.
- **Keep the existing pins** (`redis` 7.4.1, `Django` 6.1.1) instead of upgrading in the same change.
  Those are the versions the 48 tests already passed with; an upgrade is a separate, reviewable step.
  Django 6.1.2 exists, so expect a Dependabot PR.
- **Docs-only changes go straight to `main`** ([decision 003](../decisions/003-one-branch-per-task.md)).

## What I should remember
- `git fetch` before starting anything. Read ahead/behind.
- Never answer a rejected push with a forced push until you know what's on the remote.
- Run CI's exact commands locally before pushing (`make test`, `ruff check .`).
- When settings change, check every file that imports them (test settings!).
- Predict a test failure before running it. When the prediction matches, you understand the system.
- An explanation that "sounds right" isn't proof. The redis claim was tested and turned out wrong.

## Review questions
1. `git status` says "nothing to commit, working tree clean". Does that mean you're in sync with GitHub? Why or why not?
2. Your push is rejected with "non-fast-forward". List what you'd run, in order, before pushing again.
3. Why did adding `SECURE_SSL_REDIRECT = True` break tests that have nothing to do with HTTPS?
4. Code reading: in the CI step, what would happen if someone removed `--tag security`?
5. Design: we silenced W005/W021 instead of setting HSTS subdomains/preload to `True` in CI. Why is setting them `True` in CI the wrong fix?
6. You run `pip-compile` and it keeps `Django==6.1.1` even though 6.1.2 is out. Why, and how do you get 6.1.2?

<details><summary>Answer key</summary>

1. No. It only describes your local files against your local branch. Without `git fetch`, git hasn't
   checked GitHub at all.
2. `git fetch`, then `git status -sb` or `git log --oneline main..origin/main` to see what's new, then
   `git rebase origin/main` (or merge), resolve conflicts, run the tests, then a normal `git push`.
3. The test settings inherit the production settings, because DEBUG is off. Every request from the
   plain-HTTP test client got a 301 to `https://`, so the tests saw redirects instead of real responses.
4. All deploy checks would run, including drf-spectacular's W001 schema warnings. With
   `--fail-level WARNING`, CI would fail on warnings unrelated to security.
5. CI would then test a configuration production doesn't use. The check would pass while production
   silently differs. Silencing records the real decision.
6. pip-compile keeps existing pins from the output file if they still satisfy `requirements.in`.
   Run `pip-compile --upgrade-package django` (just Django) or `pip-compile --upgrade` (everything),
   then run the tests and commit.
</details>

## Next steps
- Open PRs for `t-01-settings-from-env` and `t-08-pinned-deps`, and watch CI run on GitHub.
  Merge one, update the other from `main`, then merge it.
- Delete the stale `loadtest-and-scaling-docs` branch on GitHub.
- After T-08 merges, sync your `.venv`.
- Next task: finish T-11 (refresh-token test, Postgres/Redis in CI), then T-02/T-03/T-04.
- Review beforehand: the git guide's section 7.
