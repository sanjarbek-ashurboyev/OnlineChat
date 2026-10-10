# Project overview

*Last checked against the code: 2026-10-10, `main` `05ec1f9`. Branch-only changes are marked as such.*

## What OnlineChat is

A real-time, one-to-one chat web app (like a small Telegram/WhatsApp Web):

- Sign up and log in with a **phone number** (Uzbek numbers by default: `region="UZ"`) and password.
- Start a chat with another user, send messages, see them arrive **instantly**.
- **Read receipts** (a message is marked read when the other person opens the chat).
- **Presence**: see whether the other person is online, or when they were last seen.
- Profile with an avatar image.
- A `Block` model exists, but the audit found there's no way to use it yet (COR-7).

Why it exists: it's a learning project meant to be shown to employers, and
[`docs/scaling/`](../scaling/README.md) plans how to grow it to **10,000 users online at once**.

## Architecture at a glance

```
                      ┌────────────── Browser ──────────────┐
                      │ templates/index.html + assets/app.js │
                      └───────┬────────────────────┬────────┘
               HTTP (REST)    │                    │   WebSocket
       /api/v1/... with       │                    │   /ws/inbox/?token=<JWT>
       "Authorization: Bearer"│                    │
                              ▼                    ▼
                 ┌──────────── Daphne (ASGI server) ────────────┐
                 │  root/asgi.py  ProtocolTypeRouter             │
                 │   'http'      → Django (DRF views)            │
                 │   'websocket' → AllowedHostsOriginValidator   │
                 │                 → JWTAuthMiddleware           │
                 │                 → InboxConsumer               │
                 └──────┬───────────────────────────┬───────────┘
                        │ ORM (psycopg)             │ redis-py / channels-redis
                        ▼                           ▼
                 ┌────────────┐          ┌──────────────────────────────┐
                 │ PostgreSQL │          │ Redis                         │
                 │ users,     │          │ db0 channel layer (delivery)  │
                 │ chats,     │          │ db1 cache (rate-limit counts) │
                 │ messages   │          │ db2 presence (who's online)   │
                 └────────────┘          └──────────────────────────────┘
```

Locally, Postgres 17 and Redis 7 run in Docker (`compose.yaml`, `make up`). Django runs
with `make run` (`runserver`, which uses Daphne because `daphne` is in `INSTALLED_APPS`).
There's no production deployment yet.

New to these ideas? Read [concepts/http-and-websockets.md](concepts/http-and-websockets.md)
and [concepts/django-channels-and-redis.md](concepts/django-channels-and-redis.md) first.

## Technologies and their jobs

| Technology | Version (pinned) | Job in this project |
|---|---|---|
| Python | 3.13 in CI (README: 3.12+) | Language |
| Django | 6.1.1 | Web framework: models, ORM, admin, settings |
| Django REST Framework (DRF) | 3.18.1 | The JSON API under `/api/v1/` |
| SimpleJWT | 5.5.1 | Login tokens (JWT) for the API and the WebSocket |
| Channels | 4.3.2 | WebSocket support for Django (consumers, groups) |
| Daphne | 4.2.3 | The ASGI server that holds HTTP and WebSocket connections |
| channels-redis | 4.3.0 | Lets consumers in different processes message each other through Redis |
| redis (redis-py) | 7.4.1 | Direct Redis access for presence; Django's cache backend |
| psycopg 3 | 3.3.6 | Postgres driver (`main` still lists psycopg2; T-08 switches) |
| drf-spectacular | 0.30.0 | OpenAPI schema and Swagger UI at `/api/schema/swagger-ui/` |
| django-phonenumber-field | 8.5.0 | Validates and stores phone numbers |
| Pillow | 12.3.0 | Image handling for avatars |
| python-dotenv | 1.2.3 | Loads `.env` into environment variables |

Versions come from `requirements.txt` on the `t-08-pinned-deps` branch, compiled for Python 3.13.

## Components

### `root/`: project wiring
- `settings.py`: configuration. The secret key, `DEBUG` (`DJANGO_DEBUG=True/False`) and hosts come
  from the environment ([decision 001](decisions/001-settings-from-environment.md)). The T-01 branch
  adds the production HTTPS settings.
- `settings_test.py`: settings for the test suite. SQLite in memory, an in-memory channel layer,
  local-memory cache and fast password hashing, so tests need no Postgres or Redis.
- `urls.py`: HTTP routes. Serves `/media/` only when `DEBUG` is on.
- `asgi.py`: the entry point Daphne loads. It splits traffic by protocol (diagram above).

### `accounts/`: users and login
- `models.py`: `User` replaces Django's username with `phone_number` (`USERNAME_FIELD`) and
  adds `last_seen` and `avatar`.
- `authentication.py`: `LastSeenJWTAuthentication` is SimpleJWT's authenticator plus a
  `last_seen` update, written at most once a minute (`TOUCH_INTERVAL`).
- `views.py` / `urls.py`: the endpoints below. `UserLookupAPIView` is the only throttled one
  (`user_lookup: 20/hour`).

### `chats/`: conversations and real-time delivery
- `models.py`:
  - `Chat` has `user1` and `user2`, with a database rule `user1 < user2` so one pair can't
    have two chats.
  - `Message` has `chat`, `sender`, `text`, `is_read` and `read_at`, with an index on
    `(chat, created_at)`.
  - `Block` has `blocker` and `blocked`.
- `views.py`: the chat list (with last message, unread count and online status), message
  history and sending, and marking a chat as read.
- `consumers.py`: `InboxConsumer`, **one WebSocket per signed-in user** carrying all their
  chats. `broadcast_message()` lets the REST send endpoint push to sockets too.
- `middleware.py`: `JWTAuthMiddleware` reads `?token=` from the WebSocket URL and sets
  `scope['user']`. The token goes in the URL because a browser's `WebSocket` API can't
  set headers.
- `routing.py`: maps `ws/inbox/` to `InboxConsumer`.
- `presence.py`: who's online, stored as Redis sets with a 90 s expiry.
- `management/commands/loadtest_seed.py`: creates fake users for the load test.

### Frontend: `templates/index.html`, `assets/app.js`
A single page in plain JavaScript (no framework):
- **Tokens:** keeps the access and refresh tokens in `localStorage`. A 401 triggers one
  token refresh, then the request is retried.
- **Socket:** opens one socket and sends `{"action": "ping"}` every 30 s (`PING_MS`).
- **Reconnect:** waits `1s, 2s, 4s…` up to 15 s. If the server closed with code 4401
  (not logged in), it refreshes the token first.
- **Chat list:** reloads every 45 s. That catches other people's online status changes;
  messages themselves arrive over the socket.

### `loadtest/`
`run.py` simulates many browsers. See [session 001](sessions/001-project-analysis-and-load-test.md).

### Tests, lint and CI
- `accounts/tests.py`, `chats/tests.py` (REST) and `chats/test_consumers.py` (WebSocket, through
  the full ASGI stack with `WebsocketCommunicator`) hold 48 tests.
- `test_helpers.py` has shared builders (`make_user`, `token_for`) and `FakePresenceMixin`,
  which swaps Redis presence for a dict.
- Run them with `make test`. Lint with `ruff check .` (rules in `ruff.toml`).
- `.github/workflows/tests.yml` runs Ruff, the tests and `makemigrations --check` on every push
  to `main` and on every PR.
- `README.md` has setup instructions for new developers.

## API endpoints

| Method and path | View | What it does |
|---|---|---|
| `POST /api/v1/auth/register/` | `RegisterCreateAPIView` | Create an account |
| `POST /api/v1/auth/login/` | `CustomTokenObtainPairView` | Phone + password → access and refresh tokens |
| `POST /api/v1/auth/token/refresh/` | `CustomTokenRefreshView` | Refresh token → new access token |
| `GET/PATCH /api/v1/auth/profile/` | `ProfileAPIView` | Your profile |
| `GET /api/v1/users/lookup/` | `UserLookupAPIView` | Find a user (throttled) |
| `GET /api/v1/users/<id>/` | `PublicUserAPIView` | Someone's public profile |
| `GET/POST /api/v1/chats/` | `ChatListCreateAPIView` | List your chats / start one |
| `GET/POST /api/v1/chats/<id>/messages/` | `MessageListCreateAPIView` | History (newest first) / send |
| `POST /api/v1/chats/<id>/read/` | `MarkChatReadAPIView` | Mark the other person's messages read |
| `WS /ws/inbox/?token=…` | `InboxConsumer` | Real-time messages, read receipts, ping/pong |

## Key flows

**Opening the app (WebSocket connect)**
1. `app.js` calls `new WebSocket('/ws/inbox/?token=<access>')`.
2. `AllowedHostsOriginValidator` rejects the socket if the `Origin` header isn't an allowed host.
3. `JWTAuthMiddleware` checks the token. A bad token means `AnonymousUser`.
4. `InboxConsumer.connect()` closes with code **4401** if the user is anonymous. Otherwise it:
   1. joins group `user_<id>`,
   2. accepts the socket,
   3. marks the user online in Redis,
   4. updates `last_seen`.

**Sending a message over the socket**
1. The browser sends `{"action": "message", "chat_id": 5, "text": "hi"}`.
2. `receive()` runs `get_chat()` (are you in this chat?), `is_blocked()` and `save_message()`.
   Each of these is a separate database call.
3. It calls `group_send` to `user_<sender>` and `user_<recipient>` through Redis.
4. Every consumer in those groups (each open tab) runs `chat_message()` and pushes JSON to its browser.

**Reading a chat:** `{"action": "read", "chat_id": 5}` → `mark_read()` updates the rows →
`notify_read()` sends a `read` event to both users.

**Presence:** each ping refreshes the 90 s expiry on the Redis key. When the socket closes, the
consumer removes its channel from the set. If a server crashes, the expiry cleans up.

## Current state

- Works locally. CI runs on GitHub. **No production deployment yet.**
- **Tests:** 48 on `main`, all passing. The T-01 branch adds 2 more.
- **Audit:** [docs/scaling/01-audit.md](../scaling/01-audit.md) lists every known issue.
  The fixes are tracked in [progress.md](progress.md).
