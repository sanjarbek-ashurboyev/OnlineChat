# Dependency management

**Prerequisite:** you've used `pip install` and a virtualenv (`.venv`).

## 1. Simple definition
- A **dependency** is a library your code needs. A **transitive dependency** is a library *your
  libraries* need. For example, `daphne` needs `twisted`, and you never asked for `twisted` yourself.
- **Pinning** means recording the exact version of each one (`Django==6.1.1`).

## 2. Why it exists
"It works on my machine" usually means your machine has different library versions than the server.
Pinning every package, including the transitive ones, means every install gets **the same set**:
the code you tested is the code you ship.

## 3. How it works with pip-tools
1. You write **`requirements.in`**: only the packages you use directly, with loose ranges if any.
2. `pip-compile requirements.in` works out a compatible version for every package, including the
   transitive ones, and writes **`requirements.txt`** with exact pins and `# via` comments.
3. Everyone (you, CI, servers) runs `pip install -r requirements.txt`.
4. To upgrade, run `pip-compile --upgrade` (everything) or `--upgrade-package NAME` (one package), then test
   and commit both files. Without those flags, existing pins are kept.

Analogy: `requirements.in` is the shopping list ("bread, milk"); `requirements.txt` is the receipt
(exact brand, size and price of everything, bag included).

## 4. Small example
```text
# requirements.in
daphne
```
```text
# requirements.txt (generated)
daphne==4.2.3
    # via -r requirements.in
twisted==26.4.0
    # via daphne
```

## 5. In our project (T-08)
- `requirements.in` lists 12 direct dependencies, with comments on the non-obvious ones
  (e.g. `pillow` is there for `User.avatar`).
- `requirements.txt` has 45 pinned packages, compiled with Python 3.13 (the version CI uses).
- **Version operators:**
  - `Django~=6.1.0` means "6.1.x": bug fixes allowed, not 6.2.
  - `psycopg[binary,pool]` adds *extras*: `binary` (a prebuilt C library, so nothing needs compiling)
    and `pool` (connection pooling, needed for [PERF-2](performance-and-load-testing.md)).
  - `--strip-extras` writes the extras as separate pins (`psycopg-binary`, `psycopg-pool`), so the
    file works with plain pip.
- `.github/dependabot.yml` has GitHub open a weekly pull request to bump versions.
- `pip-audit -r requirements.txt` checks pins against known vulnerabilities (CVEs).
- **Proof that it's complete:** a brand-new virtualenv plus `pip install -r requirements.txt` passed
  the Django checks. Your daily `.venv` can't prove that, because it may have extra packages that
  hide a missing line.

## 6. Alternatives
| Tool | Notes |
|---|---|
| `pip freeze > requirements.txt` | Pins everything, but mixes direct and transitive with no explanation, and includes junk you installed by hand. |
| **pip-tools** | Chosen ([decision 002](../decisions/002-pinned-dependencies-with-pip-tools.md)). Small, standard output. |
| uv (`uv pip compile`, `uv lock`) | Same idea, much faster, newer. |
| Poetry / PDM | Project manager with a lock file in `pyproject.toml`. More features, more to learn. |

## 7. Common mistakes
- **Editing `requirements.txt` by hand.** The next compile overwrites it. Edit `.in`.
- **Testing in your everyday venv only.** It hides missing packages.
- **Pinning and never updating.** Pins age into security holes. That's what Dependabot and `pip-audit` are for.
- **Compiling with a different Python version than production.** Some packages pin differently per
  Python version. Compile with the Python version you deploy; we use 3.13, like CI.
- **Expecting `pip-compile` to upgrade.** It keeps pins already in `requirements.txt` as long as they
  still fit. That's why our file kept `redis==7.4.1` and `Django==6.1.1`, though an empty file would
  get 8.1.0 and 6.1.2 (tested in [session 006](../sessions/006-syncing-with-github.md)). Use
  `pip-compile --upgrade`, or `--upgrade-package NAME`, to move on.

## 8. When to use it
For any application you deploy. (Libraries you *publish* do the opposite: wide version ranges, so
they fit into other people's apps.)
