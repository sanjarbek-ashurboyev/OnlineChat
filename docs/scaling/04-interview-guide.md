# 4. Interview guide

Update this file as you complete tasks. The golden rule: **only claim what the
"Evidence" column supports.** Interviewers respect "we measured X; Y is still untested"
far more than an unsupported "it scales to a million users".

---

## 4.1 Claims tracker: implemented vs tested vs measured vs designed

| Item | Status today | Evidence |
|---|---|---|
| Real-time chat over one WebSocket per user, Redis channel layer | Implemented (before this plan) | Code |
| Load test harness (`loadtest/run.py`, seed command) | Implemented | Ran 2026-10-09 |
| Single process healthy at 100 online (heavy profile: 50% chatting, 10 msg/min), failing at 200 | **Measured** (same-machine generator, so pessimistic) | `loadtest/results-trial.json` |
| Root cause: one shared DB thread + 6.2 ms connect per call | **Measured parts** (connect time, library source) + model; profiler confirmation pending (T-12) | 01-audit PERF-1–4 |
| Chat list runs its aggregate twice | **Measured** (query capture) | 01-audit PERF-5 |
| Disconnect bug under burst | **Observed** (97 errors) | Server log |
| Everything in stages 0–2 (target: 10,000 online) | **Designed only** | 02-plan |

When a task is done, move it up: *Designed → Implemented → Tested → Measured (with numbers)*.

---

## 4.2 The 2-minute project story (current version)

> "I built a one-to-one messenger in Django with Channels: REST for history and
> accounts, and one WebSocket per user for live delivery through a Redis channel layer,
> with Redis-based presence.
>
> To find its limits, I wrote a step load test that simulates real clients: pings, chat
> list polling, sending and read receipts, measuring end-to-end delivery latency. A
> single process stayed healthy at 100 concurrent users with a heavy messaging profile,
> and p95 latency jumped to 1.5 s at 200.
>
> I traced that to two things. Channels runs all synchronous database calls from
> WebSocket consumers on one shared thread per process. And with Django's default
> settings, each of those calls opened a new Postgres connection: 6 ms to connect
> versus 0.2 ms for the query. A delivered and read message cost seven of those calls.
> The arithmetic predicted saturation right between my two load steps.
>
> The same audit found security problems that mattered more than capacity: the secret
> key was committed to a public repository, which allows forging login tokens, and
> there was no rate limiting on login or messaging. I fixed those first.
>
> Then I planned capacity work in order of cost: connection pooling first, then removing
> unnecessary writes per message, then more processes, measuring each step."

Update the last paragraph with real before/after numbers as you complete T-01…T-17.
**Don't say "fixed" until it's merged and tested.**

---

## 4.3 Questions by topic

### Topic A: Users vs load (capacity thinking)

**L1. "How many users does your app support?"**
- **Model answer:** "That depends on what 'users' means. Registered users cost storage;
  concurrent online users cost sockets and pings; messages per second cost database
  writes. I measured about 100 concurrent users per process with a heavy chat profile.
  Converting that to registered users needs assumptions about daily activity and peak
  concurrency, which I've written down and plan to replace with real metrics."
- **Weak answer:** "About 10,000 users." It's a single number with no workload
  definition, so the interviewer can't tell if you understand capacity at all.

**L2. "Why did you express the limit as DB calls per second?"**
- **Model answer:** "Because the bottleneck was one thread doing database calls. Users,
  messages and pings all reduce to calls on that thread. That turns the question into
  arithmetic: calls per action × cost per call ÷ threads. And each optimisation attacks
  one factor."

**L3. "Traffic grows 10× overnight. What breaks first, and how would you know?"**
- **Model answer:** "On the current code, the WebSocket DB thread. Message delivery p95
  climbs sharply once that thread passes ~70% busy, because queueing delay grows
  non-linearly. I'd see it as delivery latency rising while CPU on the DB stays low.
  That combination points to the app side, not Postgres.
  - Short-term: add processes (the channel layer already routes between them) and
    raise the client poll interval.
  - Then: pooling, fewer calls per message.
  - The next limit after that is Postgres connections, then the chat list query."

### Topic B: The single shared thread and connection pooling

**L1. "Why does an async server have a single-thread bottleneck?"**
- **Model answer:** "The consumers are async, but Django's ORM is synchronous. Channels
  runs each ORM call through `database_sync_to_async`, which by default uses one shared
  thread per process to keep database connections thread-safe. Django gives each HTTP
  request its own thread context; Channels doesn't do that per WebSocket. So every
  socket's DB work queues for one thread."

**L2. "Why pooling and not just raising max_connections?"**
- **Model answer:** "The cost was *opening* connections (6 ms vs 0.2 ms for the query),
  not having too few. More connections doesn't remove the connect cost. Each Postgres
  connection is a process with its own memory, and too many active ones make the
  database slower. A bounded pool reuses connections and caps how much load the app
  can push onto the database. Under overload, requests wait briefly in the app instead
  of overloading Postgres."

**L3. "You have 12 processes with a pool of 10 each, and Postgres allows 100 connections. What now?"**
- **Model answer:** "12 × 10 = 120 > 100, so under a burst some processes can't connect.
  Options:
  - Shrink the pools (Little's law: busy connections ≈ throughput × hold time, usually far below 10 per process).
  - Or put PgBouncer in transaction mode in front, multiplexing many client connections
    onto fewer server connections. That has caveats: no server-side cursors, care with
    prepared statements, and PgBouncer itself must be highly available.
  - I'd first measure actual connection usage at peak."
- **Weak answer:** "Increase max_connections to 200." It shows no understanding of why the limit exists.

### Topic C: Delivery guarantees

**L1. "What happens to a message sent while the recipient is reconnecting?"**
- **Model answer:** "It's always saved in Postgres first, so it's never lost. But live
  delivery through the Redis channel layer is at-most-once: if the socket isn't
  connected, the notification is gone. So after reconnecting, the client asks the API
  for messages newer than the last id it has: a gap fetch. Duplicates between the
  socket and the fetch are de-duplicated by message id."

**L2. "Why not a durable queue like Kafka or Redis Streams per user?"**
- **Model answer:** "Postgres already is the durable log of messages, and 'what did I
  miss?' is one indexed query on `(chat_id, id)`. A second durable system would duplicate
  state, add an operational burden and create consistency questions between the two. I'd
  revisit it for things like multi-device sync with per-device acknowledgements, or mobile push."

**L3. "How do you prevent duplicate messages if a client retries a send?"**
- **Model answer:** "Networks give at-least-once delivery when clients retry, so I'd
  make the *effect* idempotent:
  - The client generates a UUID per message.
  - The server has a unique constraint on (sender, client_msg_id), and on conflict
    returns the existing message instead of inserting.
  - That's 'exactly-once effect', which is achievable, unlike exactly-once delivery."

### Topic D: The chat list query

**L1. "Why was the chat list slow even though it had no N+1 problem?"**
- **Model answer:** "It ran a constant 4 queries, but the main one joined every message
  in every chat to count unread messages. Its cost grew with total history. Pagination
  also re-ran the whole aggregate for the count. And it sorted by a computed value, so
  Postgres couldn't stop early at the page limit."

**L2. "Why didn't you just cache it in Redis?"**
- **Model answer:** "The chat list changes on every message: preview, order, unread count.
  A cache would need invalidating on every message for both participants, and stale
  data is visible as wrong unread badges. Rewriting the query to count only unread
  messages via a partial index removes the cost instead of hiding it. I'd cache only
  data that's read far more than it's written, and where staleness is acceptable."

**L3. "Users with 5,000 chats complain. What next?"**
- **Model answer:** "Correlated subqueries are per chat, so cost is O(chats). I'd
  denormalise into a per-member inbox table:
  - `last_message_at` and `last_read_message_id` per user per chat.
  - The list becomes an index range scan on `(user, last_message_at DESC) LIMIT 50`.
  - Unread is messages after `last_read_message_id`, and mark-read is a one-row update.
  - I'd migrate with expand/contract: new table, dual-write, batched backfill,
    verification, feature-flagged switch, then drop the old columns a release later."

### Topic E: Security under scale

**L1. "Why was a committed SECRET_KEY critical in a JWT app specifically?"**
- **Model answer:** "SimpleJWT signs tokens with SECRET_KEY by default. With the key,
  anyone can create a valid token for any user id, which is full account takeover with
  no password. And because the repo was public, the key had to be rotated, not just
  removed from git history."

**L2. "How did you design rate limits?"**
- **Model answer:** "Different keys for different abuse:
  - Per IP on anonymous endpoints, kept generous because of carrier NAT.
  - Per phone number on login, against targeted guessing.
  - Per user on authenticated actions.
  - An in-memory token bucket per WebSocket for messages.
  - Throttle state in Redis so limits are global across processes. I made throttles fail
    open if Redis is down, so a cache outage doesn't block logins."

**L3. "An attacker registers 10,000 accounts to bypass per-user limits. Now what?"**
- **Model answer:** "Per-account limits assume accounts are expensive. Here they were
  free. So:
  - Limit registration per IP and per network range.
  - Then add phone verification by SMS, with its own rate limits and a spend cap, because
    SMS-pumping fraud is real.
  - Restrict new accounts (for example, how many chats they can start on day one).
  - Watch registration and messaging anomalies."

### Topic F: Horizontal scaling of WebSockets

**L1. "Can you run two WebSocket servers? Don't users on different servers miss each other's messages?"**
- **Model answer:** "Each user's socket joins a Redis group named after the user, so any
  process can deliver to any user by sending to that group. Load balancers don't need
  sticky sessions for this: each WebSocket is one long-lived TCP connection that stays
  on one server anyway."

**L2. "Why separate HTTP and WebSocket processes?"**
- **Model answer:** "They have different load shapes and failure modes. A reconnect storm
  after a deploy shouldn't starve the REST API, and slow REST requests shouldn't delay
  message delivery. Separate pools also scale on their own metric: sockets vs requests per second."

**L3. "Redis fails over. What do users experience?"**
- **Model answer:** "In-flight notifications and group memberships are lost. Sockets
  break and clients reconnect with jitter, rejoin their groups, gap-fetch missed
  messages from Postgres, and presence rebuilds within one ping interval. Users see a
  short 'reconnecting' state and no lost messages. That's only true because the gap
  fetch exists, which is why it was one of the first tasks."

---

## 4.4 Check your understanding (answer in your own words before starting T-13)

1. Our load test failed at 200 users. Using the capacity formula, name the three
   factors you could change, and which one pooling changes.
2. Why is "add Redis caching to the chat list" a worse first step than rewriting the query?
3. A teammate says "the channel layer guarantees delivery because Redis is persistent".
   What's wrong with that?
4. Why must T-09 (gap fetch) ship before rolling deploys (T-27)?
5. Your stage 1 load test fails. Postgres CPU is 15%, app CPU is 40%, message p95 is
   2 s. Where do you look first, and why?
