# Django Channels and Redis

**Prerequisite:** [HTTP and WebSockets](http-and-websockets.md).

## 1. Simple definition
- **Channels** adds WebSocket support to Django. Each open socket gets its own **consumer**
  object, which is like a view that lives as long as the connection.
- The **channel layer** is a message bus that lets consumers send messages to each other,
  even across processes or servers. We use Redis as that bus.

## 2. Why it exists
Django's classic model is "a request comes in, a response goes out". A socket that stays open
for hours, and receives messages *from other users' actions*, doesn't fit that model. Also,
user A's socket may be held by server process 1 and user B's by process 2. They need a shared
"post office" to talk, and Redis is it.

## 3. How it works, step by step
1. **ASGI** is the async successor to WSGI. It lets one server handle HTTP and WebSockets.
   Daphne is our ASGI server.
2. `root/asgi.py` routes by protocol: `'http'` goes to normal Django, `'websocket'` goes to
   middleware and then `URLRouter`, which picks `InboxConsumer`.
3. When the socket opens, `connect()` runs. Every incoming frame calls `receive()`. When the
   socket closes, `disconnect()` runs.
4. Every consumer has a unique `channel_name` (an address in Redis).
5. A **group** is a named set of channel names. `group_add('user_7', my_channel)` subscribes this socket.
6. `group_send('user_7', {'type': 'chat.message', ...})` puts the event in Redis. Each subscribed
   consumer picks it up and Channels calls the method named after `type`, with the dot replaced
   by an underscore: `chat_message()`.
7. **Async vs sync:**
   - Consumers are `async`, but Django's ORM is synchronous (blocking). Wrapping ORM code in
     `@database_sync_to_async` runs it in a thread so it doesn't freeze the event loop.
   - By default, all such calls in one process share **one thread**. That's the bottleneck in
     the [performance guide](performance-and-load-testing.md).

## 4. Small example
```python
class EchoConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add('lobby', self.channel_name)
        await self.accept()

    async def receive(self, text_data=None, bytes_data=None):
        # Tell everyone in the lobby, including ourselves.
        await self.channel_layer.group_send('lobby', {'type': 'lobby.say', 'text': text_data})

    async def lobby_say(self, event):          # 'lobby.say' -> lobby_say
        await self.send(text_data=event['text'])
```

## 5. In our project (`chats/consumers.py`)
- **One group per user, not per chat** (`group_for_user` → `'user_<id>'`). A per-chat group would
  only reach someone who has *that* chat open. A per-user group reaches every tab they have open,
  whichever chat is showing.
- `receive()` handles `ping`, `message` and `read`. For a message:
  1. `get_chat()` checks the sender is in the chat.
  2. `is_blocked()` checks neither side has blocked the other.
  3. `save_message()` writes it to Postgres.
  4. `group_send` delivers it to both users' groups.
- `broadcast_message()` does the same delivery from synchronous code, so a message sent through the
  **REST** endpoint also reaches open sockets.
- **Redis has three jobs here, in separate databases:**
  - **db 0, channel layer:** message delivery between consumers.
  - **db 1, Django cache:** counters for the rate limit.
  - **db 2, presence:** `chats/presence.py` keeps a Redis **sorted set** per user (`online:<id>`).
    Each member is one open socket's channel name, and its **score** is the time of that socket's last
    ping (every 30 s). A socket counts while its score is less than 90 s old, so a user is online
    while at least one socket counts. An entry left behind by a crashed consumer or a killed process
    stops pinging and ages out *on its own*, even while the user's other tabs keep pinging. The key
    also has a 90 s TTL (time to live), which removes users who have gone quiet altogether.
    (Until the presence-leak fix this was a plain set with one TTL for the whole user, see
    [P-18](../problems-and-solutions.md#p-18--leftover-presence-entries-lived-as-long-as-any-other-tab).)

## 6. Alternatives
- **No channel layer, a single process:** consumers could share a Python dict. That breaks as soon
  as you run two processes.
- **Postgres LISTEN/NOTIFY** as the bus: no Redis needed, but it's less proven with Channels.
- **A different stack** (Node.js with Socket.IO, Go, Elixir/Phoenix): good at many sockets, but it
  means rewriting the app. The plan reaches 10,000 online while keeping one Django codebase
  ([docs/scaling/README.md](../../scaling/README.md)).

## 7. Common mistakes
- **Calling the ORM directly inside an `async def`.** Django raises `SynchronousOnlyOperation`. Wrap
  it in `database_sync_to_async`.
- **Treating the channel layer as reliable.** It's *at-most-once*: if nobody is listening, or the
  socket is reconnecting, the event is dropped. The database is the source of truth.
- **Fragile cleanup in `disconnect()`.** If `group_discard` raises, the next lines (mark offline) never
  run. We hit this under load and fixed it in T-02: catch and log, then do the important step anyway
  ([P-13](../problems-and-solutions.md#p-13--a-burst-of-disconnects-left-users-online-cor-2)).
- **Assuming "too many connections" means the Redis server is full.** Here it was the client-side pool:
  redis-py's `ConnectionPool` allows 100 connections per process by default, and raises instead of waiting.
- **One expiry for a whole group of items.** If *any* member's activity renews the shared TTL, a dead
  member never expires. Give each item its own timestamp (a sorted set) and count only recent ones.
- **Forgetting `type` → method naming.** `'chat.message'` calls `chat_message`. A typo means the
  event is silently ignored, or raises an error.

## 8. When to use it
Channels makes sense when you already have a Django app and need real-time features, as here. If
the whole product is real-time with hundreds of thousands of sockets, a specialised stack may fit better.
