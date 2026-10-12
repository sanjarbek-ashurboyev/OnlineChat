# File uploads and stored files

*First used in [session 024](../sessions/024-privacy-and-uploads.md) (Codex audit M-15, M-16).*

## 1. Simple definition

An **upload** is a file the browser sends inside a request, usually as `multipart/form-data` (the request body is
split into parts: one per form field, one per file). The server checks the file, saves it somewhere (**storage**), and
keeps only its **name** in the database, e.g. `avatars/face_6IFe03o.png`.

So one photo is two things: a row that points to a file, and the file. They live in different places, and keeping them
in step is your job.

## 2. Why it matters

- **Cost:** every accepted byte is stored, maybe forever, and maybe processed (thumbnails).
- **Abuse:** "it's a valid image" is not "it's a reasonable image". A tiny picture can carry megabytes of junk, and a
  small file can claim to be 50,000 × 50,000 pixels (a *decompression bomb*: small on disk, huge once decoded).
- **Privacy:** a photo someone removed should actually be gone.

## 3. How it works, step by step (Django under Daphne)

1. **The body arrives.** Django's `ASGIHandler.read_body()` reads the *whole* request body before any view runs: into
   memory, then a temporary file once it passes `FILE_UPLOAD_MAX_MEMORY_SIZE` (2.5 MiB by default).
2. **The body is parsed.** The multipart parser splits it into fields and `UploadedFile` objects.
3. **The serializer checks it.** DRF's `ImageField` asks Pillow to open and verify the file. Pillow reads the header
   (format, width, height) and checks the structure; bytes after the image's end are ignored.
4. **Our checks run** (`validate_avatar`): size in bytes, then width and height from the header.
5. **The model saves it.** The storage (`FileSystemStorage`, under `MEDIA_ROOT`) picks a free name (adding
   `_6IFe03o` if `face.png` exists) and writes the file; the row stores the name.

Step 1 is why an app can't cap uploads by itself: by the time your code runs, the bytes have arrived. The cap on the
request body belongs in the reverse proxy in front of the app (nginx `client_max_body_size`), which refuses the
request while it's still arriving.

## 4. Small example

```python
MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_AVATAR_SIDE = 4096

def validate_avatar(self, value):
    if value is None:            # the user removed their photo
        return value
    if value.size > MAX_AVATAR_BYTES:
        raise ValidationError('The photo must be 2 MiB or smaller.')
    width, height = value.image.size   # from the header; the pixels aren't decoded
    if max(width, height) > MAX_AVATAR_SIDE:
        raise ValidationError(f'The photo must be at most {MAX_AVATAR_SIDE}×{MAX_AVATAR_SIDE} pixels.')
    return value
```

| Upload | Before | After |
|---|---|---|
| 64 × 64 black PNG (91 bytes) | 200 | 200 |
| 1 × 1 PNG + 2 MiB of zeros | 200 | 400 "2 MiB or smaller" |
| 4097 × 1 PNG | 200 | 400 "at most 4096×4096" |

## 5. In our project

- **Limits:** `accounts/serializers.py`, `ProfileSerializer.validate_avatar()`. The proxy cap is still to do (the
  deployment task in [03-operations.md](../../scaling/03-operations.md)).
- **Clean-up:** `accounts/signals.py`. `pre_save` remembers the old name; `post_save` (replaced or removed) and
  `post_delete` (account deleted) delete the file **after the commit** (`transaction.on_commit`), and only if no
  account still points to it. [Decision 011](../decisions/011-delete-avatar-files-after-commit.md).
- **Tests:** `accounts/tests.py`, `AvatarTests`. Each test gets its own temporary `MEDIA_ROOT`, so it never touches
  the real `media/` folder, and uses `captureOnCommitCallbacks(execute=True)` to run the queued deletions (a `TestCase`
  never really commits).

## 6. Alternatives

- **Re-encode every upload** (open with Pillow, resize to e.g. 512 × 512, save as a new JPEG). It strips junk and
  metadata (including GPS location in phone photos), and makes every avatar small. More CPU per upload; worth it once
  avatars are shown often.
- **Direct-to-storage uploads** (the browser uploads straight to S3 with a signed URL). The app never sees the bytes;
  limits are set in the signed URL's policy.
- **`django-cleanup`** instead of our signals: the same deletion rule for every file field, as a package.

## 7. Common mistakes

- Trusting "it's a valid image" as a size check.
- Checking only bytes (a small file with huge dimensions) or only dimensions (a tiny image with junk after it).
- Thinking an in-app check limits what the server *receives*.
- Deleting the old file before the transaction commits: a rollback leaves the row pointing at nothing.
- Forgetting the other ways a row disappears: `QuerySet.delete()` and cascades send `post_delete` per row, but
  `QuerySet.update()` sends no signals at all.
- Tests that write into the real `media/` folder.

## 8. When to use it

Any time users can send files: set byte and dimension limits in the app, a body cap at the proxy, and decide when a
stored file stops being needed and who deletes it.
