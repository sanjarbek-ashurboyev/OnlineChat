# 002 · Pin all dependencies with pip-tools

- **Date:** 2026-10-10 · **Task:** T-08 · **Status:** Accepted · **Commit:** `ec6f48e` (branch `t-08-pinned-deps`)

## Problem
`requirements.txt` was missing `daphne`, `channels`, `channels-redis` and `redis`, listed the wrong
Postgres driver, and left `djangorestframework-simplejwt` unpinned. A fresh install wouldn't run the
WebSocket part of the app. See [dependency management](../concepts/dependency-management.md).

## Options considered
1. **Hand-maintained pins**, or `pip freeze`. No tool, but freeze dumps everything installed, junk
   included, with no record of *why* each package is there.
2. **pip-tools**: `requirements.in` → `pip-compile` → `requirements.txt`. The plan's recommendation.
3. **uv**: same idea, much faster.
4. **Poetry / PDM**: full project managers with lock files in `pyproject.toml`.

## Chosen: option 2
- The output is a plain `requirements.txt`. Every host, Dockerfile and CI system understands it.
- The `# via` comments explain why each transitive package is there.
- It's a small tool to learn; the concept (direct list → locked list) carries over to uv and Poetry.

## Disadvantages and limits
- `pip-compile` must be installed separately. It isn't in `requirements.txt`, because it's a developer tool.
- Pins are resolved for one Python version and platform. We compile with 3.13, to match CI. Different servers may need a recompile.
- Slower than uv on big projects. That doesn't matter at our size.

## When another option is better
- Speed or monorepos: uv.
- Publishing a package, or managing dev/test dependency groups: Poetry, PDM or uv projects.

## Consequences
- The rule: edit `requirements.in`, run `pip-compile --strip-extras requirements.in`, and commit both files.
- Dependabot opens weekly update pull requests. `pip-audit` should run in CI (T-11).
