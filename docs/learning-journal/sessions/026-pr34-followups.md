# 026 · PR #34 review follow-ups: safe avatar updates and resilient chat refreshes

- **Date:** 2026-10-12
- **Branch:** `fix-pr34-followups`, based on `origin/main` at `1cbd7a9`.
- **Workspace:** the separate `OnlineChat-codex` worktree. Claude's checkout was not edited.
- **Scope:** the five PR #34 review findings. JavaScript changes are confined to `loadChats()`.

## What changed

1. `accounts/serializers.py`: profile updates reload the user under a PostgreSQL row lock inside
   `transaction.atomic()`, then save only the submitted fields. A stale name-only request cannot
   restore the old avatar. Concurrent uploads read the preceding committed avatar before replacing it.
2. `accounts/signals.py`: cleanup exceptions are logged after commit instead of escaping as an HTTP
   error for a change that already succeeded. Shared-file and commit-order checks remain in place.
3. `assets/app.js`: page results are merged by chat id. Missing numbered pages no longer discard
   successful responses; `chatPages` shrinks to the remaining valid range.
4. Cached chats outside that range, including lookup-opened chats, get targeted refreshes through
   `GET /api/v1/chats/?chat_id=<id>`. `chats/views.py` applies the same membership query, annotations
   and blocked-peer serializer as the normal list. Missing/deleted/outsider ids return an empty page;
   invalid ids return 400. The filter is only for GET/HEAD, not chat creation.
5. New tests live in `accounts/test_profile_updates.py`, `chats/test_chat_refresh.py` and
   `chats/test_browser_refresh.py` so the existing test modules need no edits.

## Verification and regressions

Six regression tests cover the five findings (avatar overlap has two cases). Before the fixes:

| Case | Observed on the old code |
|---|---|
| Delayed name-only profile PATCH after an upload | Stored filename reverted to the deleted old avatar |
| Two overlapping uploads, using separate PostgreSQL connections | Two files remained for one current avatar |
| Storage deletion raises `OSError` | Exception escaped the after-commit callback |
| Overlapping chat pages | Duplicate id and duplicate rendered row |
| Lookup-opened chat outside loaded pages | Header still said `User 2` after a rename |
| Vanished last page | Refresh rejected with 404 instead of updating the surviving header |

The three initial filtered-list tests also failed before implementation: the parameter was ignored,
outsider selection returned unrelated own chats, and invalid ids returned 200. A fourth guard checks
that a GET-only filter cannot break POST chat creation.

Actual final verification:

- Full PostgreSQL 17 + Redis 7 suite: **166 tests, OK (1 skipped)** in 213.124 s. This included
  **28 browser tests** and the overlapping-upload test. The skipped test needed the optional load-test
  dependency `aiohttp`, not a browser or concurrency prerequisite.
- After installing `loadtest/requirements.txt`, the optional reader test plus the four final filtered-list
  tests ran against the real services: **5 tests, OK**, no skips. The POST guard was added after the
  full run; it was covered in this targeted run.
- Final `make test`: **139 tests, OK (14 skipped)** after installing the optional load-test dependency.
  Browser classes, real Redis checks and the row-lock test are intentionally skipped in SQLite;
  this result does not replace the real-service run.
- Ruff, JavaScript syntax and migration drift checks passed.
- The database and Redis containers were dedicated to this worktree, with separate ports. No test
  used Claude's service state or the application's uploaded files.

## Concepts and code walkthrough

A **transaction** groups database writes until commit. A **row lock** prevents a competing transaction
from changing the same row until the first transaction ends. They solve different problems:
`on_commit` protects rollback ordering, but does not serialize concurrent requests.
See [file uploads and stored files](../concepts/file-uploads-and-storage.md#overlapping-profile-requests)
and the addition to [decision 011](../decisions/011-delete-avatar-files-after-commit.md).

`ProfileSerializer.update()` starts the transaction, reloads with `select_for_update()`, applies the
validated fields, and saves with `update_fields`. The existing signals observe that fresh previous
filename. The cleanup callback only deletes an unreferenced file, and now logs any failure.

`loadChats()` fetches the loaded numbered pages and treats a 404 on a later page as the end of the
range. A `Map` keyed by chat id merges overlapping results into one row. Targeted requests refresh
cached chats absent from those pages. An empty targeted result removes a deleted chat's cached row.
Chats added while requests were pending are retained; a concurrent "Show more" keeps its page count.
The current active chat is selected after the awaits before redrawing its header and read receipts.
See [pagination](../concepts/pagination.md) for why numbered pages can move.

## Problems and decisions

- **Confirmed:** all five reported failures were reproduced; their fixes extend P-32 in
  [problems-and-solutions](../problems-and-solutions.md#p-32--the-chat-list-and-the-poll-showed-what-other-screens-had-hidden-or-changed).
- The first vanished-page test used an exact button name, but the button also includes preview text.
  Scoping the locator to `.chat-name` fixed the test setup. The corrected test was rerun with the old
  `app.js` and failed specifically on the 404 assertion, then passed with the fix.
- A name-only `update_fields` fix would not serialize two uploads. Reloading under a lock handles both.
- Reusing the chat-list query avoids duplicating its membership, unread and blocked-peer rules in a
  second detail endpoint. Its optional filter is declared in the OpenAPI parameters.

## What is not done

- Token refresh, initial message recovery and send reconciliation are Claude's separate work.
- Failed storage deletion is logged; automatic retry and historical orphan cleanup are not added.
- Direct ORM writes outside the profile serializer must use their own concurrency control. SQLite
  does not enforce these row locks; PostgreSQL is the production database and concurrency test target.
- Refreshing cached chats outside loaded pages costs one extra request per such chat. The chat list
  still uses numbered pages; merging by id does not make several requests a single database snapshot.

## What I should remember

- A Python model instance can be older than the database row it represents.
- An after-commit failure cannot roll back the committed profile update.
- Numbered pages can overlap or vanish. Items need stable ids; page failures need explicit handling.
- A chat opened by lookup is visible even if its numbered page was never loaded.

## Review questions

1. Why is `atomic()` alone insufficient for overlapping avatar uploads?
2. Why should a name-only PATCH save only submitted fields?
3. Why log a storage deletion failure instead of returning 500?
4. What does the targeted chat filter return for an outsider's chat?
5. Why run the concurrency test on PostgreSQL rather than SQLite?

<details>
<summary>Answers</summary>

1. Two transactions can still read the same old value; the row lock serializes their updates.
2. It prevents stale, unrelated model fields from overwriting newer database values.
3. The profile update has already committed; the failed cleanup is a separate operation.
4. An empty result page, because the filter is applied inside the requesting user's membership query.
5. PostgreSQL enforces `select_for_update`; SQLite does not provide the same row-lock behavior.

</details>

## Next steps

Review the follow-up PR, merge it after required checks, and keep the independently developed
M-20/M-22 and frontend lifecycle fixes scoped to their own branches.
