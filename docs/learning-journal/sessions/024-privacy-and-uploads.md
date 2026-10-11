# 024 · Codex audit: stale chat state, blocked peers and avatar files

- **Date:** 2026-10-11 · **Phase:** Stage 0
- **Task:** findings M-13, M-14, M-15 and M-16 from [Codex's second audit](../../scaling/05-codex-audit-2026-10-11.md)
  · **Branch:** `fix-privacy-and-uploads`
- **Files:** `chats/serializers.py`, `chats/views.py`, `accounts/serializers.py`, `accounts/signals.py` (new),
  `accounts/apps.py`, `assets/app.js`, `accounts/tests.py`, `chats/tests.py`, `chats/test_browser.py`, docs
- **Objective:** what's on screen stays current; someone who blocked you stays hidden in your chat list too; avatar
  uploads have limits; old avatar files are deleted.

## Before we started
- `main` pulled to `1abe93c` (PRs #32 and #33 merged). Session 021 had promised M-13 with the message-consistency group;
  it was left out there and done here.
- Your three choices:
  - **M-14:** keep the chat, hide the blocker's photo, online dot and last seen; keep the name
    ([decision 010](../decisions/010-blocked-peer-in-the-chat-list.md)).
  - **M-16:** our own signals, not the `django-cleanup` package
    ([decision 011](../decisions/011-delete-avatar-files-after-commit.md)).
  - **M-15:** 2 MiB and 4096 × 4096 pixels.

## What we accomplished
1. **Tests first.** 12 new tests; on the old code 9 failed, each for its own bug:
   - M-14 (REST): someone who blocked me came back with `avatar: 'http://testserver/media/avatars/face.png'`, an online
     status and a `last_seen`, while `GET /users/<id>/` answers 404;
   - M-15 (REST): a 1-pixel PNG with 2 MiB of zero bytes after it got **200**; so did 4097 × 1 and 1 × 4097 images;
   - M-16 (REST): after replacing the photo both files were on disk (`['face.png', 'face_6IFe03o.png']`); removing the
     photo or deleting the account left the file; no deletion was queued for after the commit;
   - M-13 (browser): after the 45 s poll, a chat on page 2 still showed its unread badge (`1`), and the open chat's
     header still showed the old name.

   Three are guards that passed before and must keep passing: a small photo is saved; a file another account still
   uses is kept; someone *I* blocked still shows their details.
2. **M-14:** the chat list builds `blocked_by` (who on this page blocked me) in one query, next to `presence`.
   `ChatSerializer.get_participant()` blanks `avatar`, `is_online` and `last_seen` for them.
3. **M-15:** `ProfileSerializer.validate_avatar()` rejects files over `MAX_AVATAR_BYTES` (2 MiB) and images wider or
   taller than `MAX_AVATAR_SIDE` (4096), with a 400 and a message saying the limit.
4. **M-16:** `accounts/signals.py`. `pre_save` remembers the old file name; `post_save` and `post_delete` queue
   its deletion with `transaction.on_commit`, and the deletion runs only if no account points to the file any more.
5. **M-13:** `loadChats()` fetches every chat page on screen (`state.chatPages` of them, in parallel), not only page 1,
   and redraws the open chat's header through a new `showPeer()`, also used by `openChat()`.
6. **Results:** browser suite **25 OK**. `make test` → **132 run, OK (12 skipped)**. Real Postgres + Redis →
   **157 tests, OK**. `ruff check .` clean. `makemigrations --check`: no changes. OpenAPI `--validate`: 0 errors and
   the same 13 warnings as before (M-20).

**Not done:**
- **No cap on the request body in the app.** By the time a view runs, Daphne has already received the whole body (see
  the [uploads guide](../concepts/file-uploads-and-storage.md), section 3). The cap belongs in the reverse proxy
  (`client_max_body_size 3m;` in nginx), which is already a step of the deployment task in
  [03-operations.md](../../scaling/03-operations.md).
- **Old orphaned files** already in `media/avatars/` stay. Locally the folder doesn't exist yet. A deployment that ran
  before this fix would need a one-off clean-up.
- **The poll costs one request per loaded chat page** every 45 s. Usually that's one; a user who opened 5 pages makes 5.
- **There's still no API to block someone**: blocks are only made in the database (and by tests). M-14 matters as
  soon as one exists.

## Concepts I learned
- [File uploads and stored files](../concepts/file-uploads-and-storage.md) (new guide).

### Django signals
- **Simple definition:** a hook Django calls around model events. `pre_save` runs just before a row is written,
  `post_save` just after, `post_delete` after a delete. You connect a function with `@receiver(pre_save, sender=User)`.
- **Why here:** an avatar can change through the API, the shell or a data migration, and an account can be deleted by
  `user.delete()` or `User.objects.filter(...).delete()`. All of these send the signals; only one of them goes through
  `ProfileSerializer`.
- **Where they're connected:** `AccountsConfig.ready()` imports `accounts.signals`. Without that import, the
  `@receiver` lines never run and nothing is connected.

### `transaction.on_commit`
- **Simple definition:** "run this function only if and when the current database transaction commits". If it rolls
  back, the function is thrown away.
- **Why here:** files aren't part of the database transaction. Deleting the old photo *before* the commit, and then
  rolling back, would leave the account pointing at a file that's gone.

### One rule, every door
- The profile endpoint already hid someone who blocked you; the chat list showed them anyway. Like
  [P-20](../problems-and-solutions.md#p-20--two-doors-one-lock-auth-and-rate-limits-only-on-one-transport) (REST vs
  socket), a privacy rule has to hold everywhere the same data comes out.

## Important code walkthrough

### `chats/serializers.py`: hiding someone who blocked me
```python
data = PublicUserSerializer(other, context=self.context).data
blocked_by = self.context.get('blocked_by')
if blocked_by is None:
    hidden = Block.objects.filter(blocker=other, blocked=me).exists()
else:
    hidden = other.pk in blocked_by
if hidden:
    data.update(avatar=None, is_online=False, last_seen=None)
```
- The list view computes `blocked_by` for the whole page in one query. `create()` (starting a chat) has no such map,
  so the serializer asks for the single user; the same pattern `presence` already uses.
- The result looks the same as someone who never set a photo and hasn't been online. The block stays undetectable,
  as on the lookup and profile endpoints.

### `accounts/serializers.py`: the limits
```python
if value.size > MAX_AVATAR_BYTES:
    raise ValidationError('The photo must be 2 MiB or smaller.')
width, height = value.image.size
if max(width, height) > MAX_AVATAR_SIDE:
    raise ValidationError(...)
```
- `value.image` is set by Django's `ImageField` check, which opened the file with Pillow. Pillow reads the size from
  the file's header without decoding the pixels, so a huge image is rejected cheaply.

### `accounts/signals.py`: deleting after the commit
```python
@receiver(pre_save, sender=User)
def remember_old_avatar(sender, instance, update_fields=None, **kwargs):
    if instance.pk is None or (update_fields is not None and 'avatar' not in update_fields):
        instance._old_avatar = ''
        return
    instance._old_avatar = sender.objects.filter(pk=instance.pk).values_list('avatar', flat=True).first() or ''

def delete_when_unused(name):
    def delete():
        if not User.objects.filter(avatar=name).exists():
            User.avatar.field.storage.delete(name)
    transaction.on_commit(delete)
```
- `pre_save` costs one small query per save. Login saves with `update_fields=['last_login']`, so it's skipped there;
  `last_seen` is written with `.update()`, which sends no signals at all.
- "No account points to it" protects a file that two rows share (only possible if someone sets it by hand, but a
  deleted photo can't be undone).

### `assets/app.js`: the poll covers every page and the header
```js
const urls = Array.from({ length: state.chatPages }, (_, i) => (i ? `/chats/?page=${i + 1}` : '/chats/'));
const pages = await Promise.all(urls.map((url) => api(url)));
...
if (urls.length === state.chatPages) $('more-chats').hidden = !pages[pages.length - 1].next;
...
showPeer(active.participant);
```
- If "Show more chats" finishes while a poll is in flight, the poll's answer is older, so it doesn't decide whether
  the button shows.

## Problems we encountered
- [P-32 · The chat list and the poll showed what other screens had hidden or changed](../problems-and-solutions.md#p-32--the-chat-list-and-the-poll-showed-what-other-screens-had-hidden-or-changed)
- **A browser test failed for the wrong reason.** `has_text='User 2'` also matched "User 20" to "User 29" (the test
  has 51 chats), so the first run failed with a Playwright "strict mode violation", not the bug. Fixed by matching
  the name exactly (`re.compile('^User 2$')`); GOTCHA has the rule.

## Engineering decisions and trade-offs
- [Decision 010](../decisions/010-blocked-peer-in-the-chat-list.md): keep the chat, blank the blocker's details.
- [Decision 011](../decisions/011-delete-avatar-files-after-commit.md): our own signals, deleting after the commit.
- **Re-fetch every loaded page** rather than add an `?ids=` filter to the API: no API change, and it also brings back
  chats whose position changed.
- **Limits in the serializer, not on the model field.** A model validator would need a migration and also cover the
  admin, but `User` isn't in the admin; the API is the only way in.

## What I should remember
- A privacy rule has to hold on every endpoint that returns the same data.
- Validate the size *and* the dimensions of an image: "it's a valid PNG" says nothing about either.
- An app can't refuse bytes it has already received. Cap the request body at the proxy.
- Files live outside the database transaction: delete them in `on_commit`, never before.
- Anything drawn once (a header, a page) goes stale unless something redraws it.

## Review questions
1. Before this fix, how could someone who was blocked still see the blocker's online status?
2. Why do we blank `avatar`, `is_online` and `last_seen` instead of removing the chat?
3. The 1-pixel PNG with 2 MiB of junk after it: why did Django's `ImageField` accept it?
4. Why doesn't `validate_avatar` stop a 1 GB upload from costing the server anything?
5. What goes wrong if the old avatar is deleted in `post_save` directly, without `on_commit`?
6. Why does `remember_old_avatar` skip the query when `update_fields` doesn't include `avatar`?
7. The user loaded 2 chat pages. What did the 45 s poll refresh before, and what now?

<details><summary>Answer key</summary>

1. `GET /users/<id>/` returned 404, but `GET /chats/` serialized the participant with `PublicUserSerializer`, which
   includes `is_online`, `last_seen` and `avatar`, with no block check.
2. It's the user's own conversation history, and removing it would reveal the block. Blanked details look the same as
   someone who never set a photo and hasn't been online lately (decision 010).
3. The check only asks Pillow "is this an image?". Pillow reads the PNG and stops at its end marker; bytes after it
   are ignored. Nothing checked the file size.
4. Under Daphne, Django's `ASGIHandler.read_body()` receives the whole body (into memory, then a temporary file past
   2.5 MiB) before the view runs. The serializer can only refuse to *keep* it. The proxy has to refuse to *receive* it.
5. If the transaction then rolls back, the row still points to the old file, which is gone: a broken photo.
6. Then the save can't change the avatar (for example login saves `last_login` only), so there's nothing to compare
   and the extra query is wasted.
7. Before: page 1 only; page 2 kept old unread counts and online dots, and the open chat's header never changed after
   opening. Now: pages 1 and 2, in parallel, and the header is redrawn from the fresh data.
</details>

## Next steps
- Open the PR, let CI run, merge.
- Remaining audit items: contracts and test infrastructure (M-20, M-22), and the risks R-01…R-07.
- Cap the request body at the proxy when the deployment task is done (`03-operations.md`).
