# 011 · Delete old avatar files with our own signals, after the commit

- **Date:** 2026-10-11 · **Status:** Accepted (chosen by you in session 024)

## Problem
Codex audit M-16: replacing or removing a photo, or deleting the account, left the old file in `media/avatars/`
forever. Storage grew, and photos people had removed were kept.

## Options considered
1. **Our own signals** in `accounts/signals.py` (about 30 lines): remember the old name in `pre_save`, then delete it
   in `transaction.on_commit` from `post_save` and `post_delete`, if no account points to it.
2. **The `django-cleanup` package:** the same idea for every `FileField`, with no code of ours.
3. **Delete in `ProfileSerializer.update()`:** the shortest, but blind to the shell, data migrations and deleting
   accounts.

## Chosen: option 1
- One file field, one model: a package for that is more to keep up to date than the code it saves.
- Every step is visible and tested (replace, remove, delete account, shared file, deletion only after the commit).
- Signals cover every way a `User` changes or is deleted, not only the API (option 3's gap).

## Disadvantages and limits
- `pre_save` costs one small query per `User` save that might change the avatar. Saves that name their fields without
  it (login's `last_login`) skip it, and `.update()` sends no signals.
- `QuerySet.update(avatar=...)` sends no signals, so it would leave the old file. Nothing does that today.
- Files orphaned before this fix stay; a one-off clean-up would be needed on a server that ran the old code.

## PR #34 follow-up: serialize profile replacements

[Session 026](../sessions/026-pr34-followups.md) reproduced loss of a replacement photo when a
stale name-only request saved the old filename, and an orphan after overlapping uploads.
`on_commit` solves rollback ordering; it does not serialize requests.

The profile serializer now reloads the user with `select_for_update()` inside `atomic()` and
saves only the submitted fields. Merely specifying `update_fields` would fix the name-only
case but leave two uploads racing. Moving cleanup before commit would break rollback safety.
Keep the signals for replacement/removal/deletion and shared-file checks; catch and log callback
failures so a committed profile update still succeeds. Failed deletions require later cleanup;
automatic retries and historical orphan removal remain outside this change.

## When another option is better
- **`django-cleanup`** once several models have files (attachments, voice notes): one well-tested rule for all of them.
- **A periodic sweep** (list the files, delete those no row references) if files ever live on storage where deleting
  inside a request is slow, e.g. S3 with many files.
