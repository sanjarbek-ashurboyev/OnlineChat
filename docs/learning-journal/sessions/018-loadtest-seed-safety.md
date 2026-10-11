# 018 · Codex audit: a seed command that can't delete real people

- **Date:** 2026-10-11 · **Phase:** Stage 0
- **Task:** findings H-05, M-21, L-01 and L-02 from [Codex's second audit](../../scaling/05-codex-audit-2026-10-11.md)
  · **Branch:** `fix-loadtest-seed-safety`
- **Files:** `chats/management/commands/loadtest_seed.py`, `chats/test_loadtest_seed.py` (new), `loadtest/run.py`,
  `loadtest/verdict.py`, `loadtest/test_verdict.py`, `loadtest/test_run.py` (new), `Makefile`, docs
- **Objective:** load-test tooling that can never touch real accounts, judges the error rate the way the plan
  states it, and never counts a dead socket as online.

## Before we started
- PR #27 (session 017) merged as `2271f93`. Codex audited `e969471`; `git diff e969471 2271f93` is empty, so
  every finding still applied. Branched `fix-loadtest-seed-safety` from the updated `main`.
- The audit lived in `/private/tmp`, which macOS clears on reboot. It is now
  [docs/scaling/05-codex-audit-2026-10-11.md](../../scaling/05-codex-audit-2026-10-11.md), with fixed items ticked.

## What we accomplished
1. **H-05: the seed command could delete real users.** Three separate faults:
   - Seed users were found by phone prefix `+998990` plus first name `loadtest`. `phonenumbers` says
     `+998990000001` is a **valid** Uzbek number, so a real person called "loadtest" matched.
   - The old users were deleted **before** the arguments were checked: `--users 0` raised an error after the delete.
   - The delete ran **outside** the transaction that creates the new users, so a failed create left nothing.

   Fix: the prefix is now `+998000`, which `phonenumbers` rejects (checked for 000000, 000001, 123456, 999999), so
   registration refuses it (a test proves the API answers 400). All arguments (`--users`, and new checks for
   `--messages` and `--token-hours`) are checked before anything changes. The delete moved inside
   `transaction.atomic()`.
2. **L-01: exactly 0.1% errors passed.** The plan says errors **< 0.1%**, but `verdict.py` failed only on `>`.
   Now `>=`, with a guard so a limit of 0 doesn't fail a step that had no errors.
3. **M-21: a crashed reader left its socket "connected".** `SimUser.read()` set `closed = True` after the loop, so an
   exception skipped it. Session 017 relied on that flag to count online users. Now it is set in `finally`, which also
   cancels the user's ping/poll/send loops and closes the socket.
4. **L-02: `make psql` hard-coded `onlinechat_user`/`onlinechat`.** It now reads `$POSTGRES_USER`/`$POSTGRES_DB`
   inside the container, which Compose fills from `.env`.
5. **Results:**
   - New seed tests on the old command: **4 of 5 tests failed**, 7 failures in all, because each of the 4 bad
     arguments fails as its own subtest. The fifth ("reseeding replaces users") already worked. All 5 pass after the fix.
   - Verdict test for the 0.1% boundary failed first, passes now. Reader test failed first (`closed` stayed False),
     passes now.
   - `make test` → **96 run, OK (6 skipped)**. Real Postgres + Redis (`python manage.py test`) → **102 tests, OK**,
     browser tests included. `ruff check .` (0.16.10) → clean.
   - Real tools: seeded 4 users, ran `loadtest/run.py` against `runserver` → `4 online, 18 sent, msg95 102 ms, OK`,
     then `loadtest_seed --delete` removed them. `make psql` opened `psql (17.11)` on `onlinechat`.

**Not done:**
- `loadtest/test_run.py` needs `aiohttp`, which CI doesn't install, so **CI skips it**. It runs locally (your `.venv`
  has aiohttp 3.14.4).
- Your local database still has **40 old seed users** with the `+998990` prefix. The new command no longer recognises
  them, on purpose. Remove them once by hand if you like (see "Next steps").
- A reader crash now counts as a drop but isn't reported separately. asyncio still prints the exception
  ("Task exception was never retrieved"), so it isn't silent.

## Concepts I learned

### Test data must be impossible to confuse with real data
- **Simple definition:** fake records are marked by something a real record **cannot** have, not something it
  probably won't have.
- **Why:** "probably" fails at scale. A name anyone can type is not a marker.
- **Here:** an invalid phone range. Registration validates numbers with `phonenumbers`, so a real account can't
  get one. The name `loadtest` stays as a second check.
- **Alternatives:** a separate load-test database (strongest), or a database field like `is_loadtest` (needs a migration).

### Check everything, then change anything
- **Simple definition:** validate all inputs before the first write.
- **Everyday example:** a cashier counts your money before giving the change, not after.

### `transaction.atomic()` makes "replace" safe
- Delete-then-create inside one transaction is all or nothing. If the create raises, Postgres rolls the delete back.

### `try`/`finally` for state that must always be updated
- Code after a loop runs only when the loop **ends normally**. Code in `finally` runs on normal exit, on an
  exception and on cancellation.

### `>` versus `>=` at a limit
- "Must be under 0.1%" fails at 0.1%. "Must not exceed 0.1%" passes at 0.1%. Read which one the requirement says,
  then write a test **at** the boundary, not just on each side of it.

## Important code walkthrough

### `loadtest_seed.py`: check, then replace in one transaction
```python
count = opts['users'] + opts['users'] % 2
if not 2 <= count <= 999_999:
    raise CommandError('--users must be between 2 and 999999.')
...
with transaction.atomic():
    loadtest_users().delete()
    users = User.objects.bulk_create(...)
```
- Nothing is deleted until every argument is known to be fine.
- `--delete` alone still deletes straight away: that's its whole job.

### `loadtest/verdict.py`
```python
if bad and bad / total >= max_errors:
```
- `bad and` matters: with `--max-error-rate 0`, `0 / total >= 0` would be True and every clean step would fail.

### `SimUser.read()` in `loadtest/run.py`
```python
try:
    async for frame in self.ws:
        ...
finally:
    self.closed = True
    if not self.run.stopping:
        self.stats.drops += 1
    for task in self.tasks:
        if task is not asyncio.current_task():
            task.cancel()
    await self.ws.close()
```
- `read` is one of the tasks in `self.tasks`; it must not cancel itself while cleaning up.

### `chats/test_loadtest_seed.py`
```python
with mock.patch.object(Chat.objects, 'bulk_create', side_effect=RuntimeError), \
        self.assertRaises(RuntimeError):
    self.seed(users=4)
self.assertEqual(loadtest_users().count(), 2)
```
- Forces the create to fail halfway and checks that the previous users survived.

## Problems we encountered
- [P-24 · The load-test seed command could delete real accounts](../problems-and-solutions.md#p-24--the-load-test-seed-command-could-delete-real-accounts)
- **My first version of the bad-arguments test checked less than it seemed.** Two mistakes:
  - The helper passed `messages=0` and the subtest passed `messages=-1`, so `call_command` got the argument twice and
    raised `TypeError`. Fixed by merging the dicts.
  - The count check sat *after* the `with self.subTest(...)` block, so the first failure (`users=0`) ended the whole
    test and the other three cases never ran. That is also why the `TypeError` stayed hidden on the old code.
    Moved inside the subtest; now each case fails on its own against the old command.

## Engineering decisions and trade-offs
- **Invalid phone range rather than a new field or database:** no migration, and registration's own validation is the
  guarantee. Trade-off: seed numbers won't pass `full_clean()`, which is fine because they're created with
  `bulk_create` and never edited.
- **The reader test skips without aiohttp** rather than adding aiohttp to the app's requirements. The load tester's
  dependencies stay separate.

## What I should remember
- A marker for fake data must be something real data **can't** have.
- Validate first, mutate second; replace inside one transaction.
- State that must always be updated goes in `finally`.
- Test exactly at a limit, and read whether the rule says `<` or `<=`.
- Put every assertion of a case *inside* its `subTest`, or the first failure hides the rest.

## Review questions
1. Why was `first_name='loadtest'` not enough to protect real users?
2. Before the fix, what happened with `loadtest_seed --users 0`? After?
3. Why is `loadtest_users().delete()` now *inside* `transaction.atomic()`?
4. Why does `too_many()` start with `bad and`?
5. Session 017 said each socket's `closed` flag "never resets". What was still wrong with it?
6. Why does CI skip `loadtest/test_run.py`, and why is that acceptable here?

<details><summary>Answer key</summary>

1. Anyone can register with that first name, and `+998990…` is a valid Uzbek number range. Both markers could
   belong to a real person.
2. Before: all users matching the markers were deleted, then `CommandError` was raised, so nothing replaced them.
   After: `CommandError` before any write; nothing changes.
3. So the delete and the create succeed or fail together. If creating fails, the rollback restores the old users.
4. With a limit of 0, `0 / total >= 0` is True, so a clean step would fail. `bad and` skips steps with no errors.
5. It was set *after* the reading loop. An exception while handling a frame skipped that line, so a dead socket
   stayed "open" and was counted as online.
6. It imports `run.py`, which needs `aiohttp`; CI installs only the app's requirements. It runs wherever the load
   tester runs (your `.venv`), which is where a regression would matter.
</details>

## Next steps
- Review and merge this PR.
- Optional: remove the 40 old seed users from your local database once:
  `python manage.py shell -c "from accounts.models import User; User.objects.filter(phone_number__startswith='+998990', first_name='loadtest').delete()"`
- Next PR from the audit: account security (H-02, H-03, M-17, M-18, M-19).
