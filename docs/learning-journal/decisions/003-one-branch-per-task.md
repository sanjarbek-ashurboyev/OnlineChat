# 003 · One git branch per backlog task, from `main`

- **Date:** 2026-10-10 · **Status:** Accepted

## Problem
Several independent tasks (docs, T-01, T-08) were happening in a row. Mixing them on one branch
makes reviews harder, and if one change is bad you can't drop it without dropping the rest.

## Options considered
1. Commit everything straight to `main`.
2. **One branch per task, named `t-NN-short-name`, branched from the latest `main`**; land it through a pull request.
3. One long-lived "development" branch (git-flow style).

## Chosen: option 2
- Each PR shows exactly one task's diff, which is easy to review and easy to revert.
- It matches the backlog numbering, so `t-01-…` maps to T-01 in `docs/scaling/03-operations.md`.
- Shared changes (docs, `.gitignore`) land in `main` first. Task branches are rebased onto it
  (see [git concepts](../concepts/git-branches-merge-rebase.md)).

## Disadvantages and limits
- Tasks that depend on each other must be landed in order, or stacked.
- Rebasing a pushed branch needs a `--force-with-lease` push ([P-06](../problems-and-solutions.md#p-06--after-the-rebase-the-local-and-github-copies-of-the-t-01-branch-diverged)).

## Additions (2026-10-10)
- **Fetch first:** before branching, run `git fetch` and make sure `main` isn't behind `origin/main`
  ([P-09](../problems-and-solutions.md#p-09--local-main-was-five-commits-behind-github)).
- ~~Docs-only changes go straight to `main`.~~ Replaced the same day, see below.

## Update 2026-10-10: a pull request for everything, enforced
- **Every** change, docs included, goes through a PR. CI then runs before the change lands, every change
  is one reviewable and revertable unit, and the history shows how the work was done.
- It's enforced by a GitHub ruleset, `protect-main`, on the default branch:
  - a PR is required (0 approvals, since you can't approve your own PR);
  - `lint`, `test`, `test-postgres-redis` and `secrets` must pass;
  - the branch must be up to date with `main`;
  - no forced pushes, no deletion, and an empty bypass list.
- You created the ruleset yourself. It's a guardrail on everyone who pushes, including the AI, so the AI
  shouldn't set it up.

## When another option is better
Working completely alone on throwaway experiments: committing to `main` is fine.
