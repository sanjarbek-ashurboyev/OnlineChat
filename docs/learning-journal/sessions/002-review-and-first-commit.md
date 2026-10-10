# 002 · Review, first commit and push

- **Date:** 2026-10-10 · **Phase:** Stage 0 setup
- **Files:** `.gitignore`, everything from [session 001](001-project-analysis-and-load-test.md)
- **Objective:** check the uncommitted work, then commit it on a new branch and push it.

## What we accomplished
- **Checked:** `git status`, `manage.py check`, `makemigrations --check`, `manage.py test`, a secrets
  search, and the seed script read against the models.
- **Found** `__pycache__/` folders about to be committed, and fixed `.gitignore`.
- **Committed** on a new branch `loadtest-and-scaling-docs` (`4de99ca`) and pushed it.
- **Found** the GitHub repository had moved. The remote change was blocked for the AI, so you need to run it.
- **Test result:** **0 tests**. The project has none, which is a finding in itself (task T-11).

## Concepts I learned
- **Branches and pushing:** [git-branches-merge-rebase](../concepts/git-branches-merge-rebase.md)
- **Why token files must never be committed:** [authentication-and-jwt](../concepts/authentication-and-jwt.md)

## Important code walkthrough
`.gitignore` after this session:
```text
.env                    # local secrets
.venv/                  # virtualenv, rebuilt from requirements.txt
loadtest/tokens.json    # live login tokens
loadtest/results*.json  # load test output
__pycache__/            # Python bytecode cache
*.pyc
```
Each line is either a secret, something that can be rebuilt, or machine-specific. That's the test
for what to ignore.

## Problems we encountered
- [P-01 · `__pycache__/` almost committed](../problems-and-solutions.md#p-01--__pycache__-folders-were-about-to-be-committed)
- [P-02 · The repository had moved](../problems-and-solutions.md#p-02--the-github-repository-had-moved)
- [P-03 · Auto mode refused the remote change](../problems-and-solutions.md#p-03--claude-codes-auto-mode-refused-the-remote-change-and-a-push)
- [P-04 · `makemigrations` couldn't reach Postgres](../problems-and-solutions.md#p-04--makemigrations---check-warned-it-couldnt-connect-to-postgres)

## Engineering decisions
- Commit on a branch, not on `main`: [decision 003](../decisions/003-one-branch-per-task.md).

## What I should remember
- Review before committing: anything pushed to a public repository should be treated as public forever.
- "0 tests ran" is not "tests pass".
- Stage explicit paths, and read `git status` first.

## Review questions
1. Which of these belong in `.gitignore`, and why: `.env`, `.env.example`, `requirements.txt`, `media/` uploads?
2. `makemigrations --check` printed a connection error *and* "No changes detected". Can you trust the result?
3. Why is pushing to a redirected repository URL risky long-term?

<details><summary>Answer key</summary>

1. `.env`: yes, it holds secrets. `.env.example`: no, it documents the variables and has no secrets.
   `requirements.txt`: no, it's needed to install. `media/` uploads: yes. They're user data, and
   they're already tracked in git, which is a leftover to clean up.
2. Yes, for its purpose. Comparing models to migration files doesn't need the database; only the
   history-consistency check does, and that's why it warned.
3. If anyone creates a repository at the old name, your pushes would go there.
</details>

## Next steps
- You: run `git remote set-url origin https://github.com/sanjarbek-ashurboyev/OnlineChat.git`.
- Start T-01.
