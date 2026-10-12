# Reliable delivery and reconnects

*First used in [session 011](../sessions/011-t09-gap-fetch-and-jitter.md) (T-09).*

## 1. Simple definition

A live connection (our WebSocket) **will** drop: Wi-Fi changes, a phone sleeps, a server restarts.
**Reliable delivery** means that, after reconnecting, the user still sees every message, none
missing and none doubled. A **gap fetch** is one way to get it: after reconnecting, ask the database
"what did I miss?".

## 2. Why it exists

Our live path is the Redis **channel layer**, and it's **at-most-once**: each notification is delivered
once or not at all, never repeated. Nothing is stored for a socket that's gone. `channels_redis` also drops
notifications that wait longer than 60 s, or when 100 are already queued
([COR-1](../../scaling/01-audit.md)).

So if your friend sends 3 messages while your socket is reconnecting, those notifications are simply
lost. The messages are safe in **Postgres** (the *source of truth*), but the open chat never shows them.

Delivery guarantees, from weakest to strongest:

| Guarantee | Meaning | Example |
|---|---|---|
| At-most-once | Maybe lost, never duplicated | Our channel layer |
| At-least-once | Never lost, maybe duplicated | A queue that retries until acknowledged |
| Exactly-once (*effectively*) | At-least-once **plus** removing duplicates | Gap fetch + de-duplication by id (what we do) |

## 3. How it works here, step by step

1. The client remembers which message ids it has shown (`state.seenIds` in `assets/app.js`).
2. The socket drops. The client waits a **random** time (see jitter below), then reconnects.
3. In `onopen`, if this is a reconnect and a chat is open, it calls
   `GET /api/v1/chats/<id>/messages/?after=<largest id shown>`.
4. The server returns only messages with a larger id, **oldest first** (`chats/views.py`).
5. The client appends them. `appendMessage` skips any id it has already shown, so a message that came both
   through the socket *and* the fetch appears once.
6. If more than one page (50) was missed, the client just reloads the chat instead.
7. It also reloads the sidebar (`loadChats()`), so unread counts and previews catch up.

The **cursor** is `Message.id`. Ids only grow, so "everything after id 41" is exact. A timestamp is
not: two messages can share one.

## 4. Small example

```
id 41  "see you"      ← shown, socket alive
       --- Wi-Fi drops ---
id 42  "are you there?"   (notification lost)
id 43  "hello??"          (notification lost)
       --- reconnect ---
GET ...?after=41  →  [42, 43]   ← appended, oldest first
```

## 5. Jitter: why reconnects need randomness

When the server restarts, **every** client loses its socket at the same moment. With a fixed backoff
(1 s, 2 s, 4 s…), they all come back at the same moment too: 10,000 reconnects in the same second, then
again 2 s later. That's a **thundering herd** ([COR-4](../../scaling/01-audit.md)), and now each
reconnect also makes a gap fetch.

**Full jitter** picks a random wait between 0 and the backoff:

```js
const delay = Math.random() * Math.min(1000 * 2 ** state.retry++, 15000);
```

The reconnects spread evenly over the window instead of arriving as a spike.

### Answers that never come (session 021)

A socket can look open while nothing gets through: a laptop wakes from sleep, Wi-Fi changes, a proxy
drops the connection silently. And the channel layer can drop one notification, such as our own echo.
Two deadlines cover both:

- **Liveness:** every 30 s the page pings. If no frame at all arrived for 30 s + 10 s, the connection is
  treated as dead: close it and reconnect (through the jittered backoff).
- **Acknowledgement timeout:** a sent message waits for its echo for 10 s at most. Then the page asks the
  history whether it was saved: if yes, it shows it and clears the composer; if not, it keeps the text and
  says the message may not have been sent. Before, one lost echo blocked every later send.
- **Pending until it's settled** (session 026): while the page asks the history, the message is still "in
  flight", so Enter can't send the same text again. Only an answer (the echo, the history check), logout or a
  dead socket settles it.

### Sessions in the browser (session 021)

A request or timer started before logout can finish after it. `state.session` is a number that `logout()`
bumps; `api()` and `refreshAccess()` remember it when they start, and an answer for an older session is
**dropped**: it returns a promise that never settles, so the caller's next step (draw the chats, save
the tokens) never runs.

**Check before acting on the answer, not only before using it** (session 026). The check used to come after
`api()`'s "401 → refresh → send again" step. A late 401 from account A, arriving after B signed in, refreshed with
**B's** token and sent A's request again as B. The session is now checked right after `fetch` returns, before
any refresh or retry.

### The sync boundary (session 023)

Catch-up used to start after the newest message *seen*. A message lost live before it was then never fetched.
`state.syncedUpTo` is the newest id we know we hold **everything** up to: the first history page sets it, catch-up
(`?after=syncedUpTo`) moves it, live messages don't. Catch-up runs on every connect, the first one included.

**Snapshot vs subscription** (session 026). Two sources fill the chat: a *snapshot* (the history request) and a
*subscription* (the socket). A message newer than the snapshot but older than the subscription is in neither.
If the socket becomes ready while the history is loading, catch-up can't start yet (there's no boundary), so it
is remembered (`state.catchUpDue`) and runs as soon as the history is in. Before, it just gave up.

### Read receipts as a boundary (session 022)

"Read" is a statement about the screen. The page sends `up_to`, the newest message id it has drawn; the server
marks the other person's messages with `id <= up_to` and tells both sides `{type: 'read', up_to}`; the sender ticks
✓✓ only up to that id. A receipt can be lost like any event, so the chat list also carries `peer_read_up_to`, and
the 45 s poll (or a reconnect) repairs the ticks.

## 6. Alternatives

| Option | How | Why not now |
|---|---|---|
| **Gap fetch** (ours) | Ask Postgres after reconnecting | Chosen: one indexed query, no new system |
| Durable queue per user (Redis Streams, Kafka) | Server stores undelivered messages, replays on reconnect | A second store to run, size and back up, duplicating Postgres |
| Sequence numbers per chat | Each message gets 1, 2, 3… in its chat; a gap is visible on *every* message | Better for multi-device sync; revisit later ([Decision 0.3](../../scaling/02-plan.md)) |

## 7. Common mistakes

- **Treating the live stream as complete.** Notifications are hints; the database is the truth.
- **Using a timestamp as the cursor.** Equal timestamps get skipped or repeated. Use a growing id.
- **Catching up from the newest message seen.** One lost live event before it becomes a permanent hole. Catch up
  from a boundary only fetches move (`syncedUpTo`).
- **Forgetting to de-duplicate.** A message can arrive by socket *and* by fetch.
- **Reconnecting without jitter.** Every deploy becomes a self-inflicted load spike.
- **Waiting forever for an answer.** Every "wait for X" needs a deadline and a plan for when it passes.
- **Letting work from before logout finish after it.** It can sign the old user back in or show their chats
  to the next one. Tag async work with a session and drop stale answers.
- **Signing out on any error.** A network blip isn't a refused token. Sign out only when the server says
  the credentials are bad (401 after a failed refresh); retry everything else.
- **Retrying instantly in a special case.** Our "token expired" path used to reconnect immediately. If
  the server kept refusing, that would be a tight loop. Every retry should go through the backoff.

## 8. When to use it

Whenever a push channel (WebSocket, SSE, mobile push) carries data that also lives in a database. Push
for speed, fetch for completeness.
