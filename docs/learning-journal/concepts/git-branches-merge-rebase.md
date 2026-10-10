# Git branches, merge and rebase

**Prerequisite:** you can commit and push.

## 1. Simple definition
- A **commit** is a snapshot of the project, with a pointer to the commit before it.
- A **branch** is just a movable label pointing at a commit.
- **Merge** combines two branches' histories. **Rebase** replays your commits on top of another branch.

## 2. Why it exists
Work in progress shouldn't break `main`. Each task gets its own branch. When it's reviewed and
working, it joins `main`, usually through a pull request (PR) on GitHub.

## 3. How it works
```
Before:           main ─ A ─ B              (B = docs)
                         └─ C               (C = T-01, branched from A)

Fast-forward merge of B into main: main had no new commits of its own, so the
label just slides forward. No new commit is created.

Rebase C onto main:  A ─ B ─ C'             (C' is a NEW commit with the same changes)
```
- A rebase creates new commits with new IDs. If the old ones were already pushed, the remote still
  has `C` and you have `C'`. A normal push is refused, because it would throw `C` away.
- `git push --force-with-lease` overwrites the remote **only if it still points where you last saw
  it**. If someone else pushed in the meantime, it refuses. A plain forced push overwrites blindly.

## 4. Small example
```bash
git checkout -b t-01-settings-from-env main   # new branch from main
# ...edit, commit...
git checkout main && git merge --ff-only docs # fast-forward only; fails if not possible
git checkout t-01-settings-from-env && git rebase main
git push --force-with-lease origin t-01-settings-from-env
```

## 5. In our project
- **Branches so far:**
  - `loadtest-and-scaling-docs`: its commits were rebased onto GitHub's `main`; the branch is stale now.
  - `t-01-settings-from-env`: rebuilt from the current `main` (`9d3ef86`) and pushed with `--force-with-lease`.
  - `t-08-pinned-deps`: rebuilt from the current `main` (`ec6f48e`).
- **The big lesson ([P-09](../problems-and-solutions.md#p-09--local-main-was-five-commits-behind-github)):**
  the local `main` was 5 commits behind GitHub for this whole time. Always `git fetch` before starting.
- **Convention:** one branch per task, named `t-NN-short-name`
  ([decision 003](../decisions/003-one-branch-per-task.md)).
- **Remote:** `origin` should be `https://github.com/sanjarbek-ashurboyev/OnlineChat.git`
  ([P-02](../problems-and-solutions.md#p-02--the-github-repository-had-moved)).

## 6. Alternatives
- **Merge commits instead of rebasing:** history keeps the true shape, but gets noisy with many small tasks.
- **Squash merge on GitHub:** each PR becomes one commit on `main`. That's a popular default.
- **Committing straight to `main`:** fine alone on a toy project. Here it'd make reviews and rollbacks harder.

## 7. Common mistakes
- **Starting work without `git fetch`.** Your `main` may be days behind GitHub's. Check
  `git status -sb` after fetching: `behind N` means pull first.
- **Rebasing a branch others are working on.** You rewrite their history. Rebase only your own branches.
- **A plain forced push instead of `--force-with-lease`.**
- **`git add .`**, which picks up caches, `.env` or token files. Stage explicit paths and read `git status`.
- **Forgetting which branch you're on.** Files "disappear" when you switch
  ([P-05](../problems-and-solutions.md#p-05--settingspy-changed-on-disk-after-switching-branches)).

## 8. When to use it
Branch for every change you'd want reviewed or might want to undo. Rebase to update your own
branch before a PR. Merge (or squash) to land it.
