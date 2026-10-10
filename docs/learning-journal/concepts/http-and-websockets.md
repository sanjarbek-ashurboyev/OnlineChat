# HTTP and WebSockets

**Prerequisite:** you know that a Django view gets a request and returns a response.

## 1. Simple definition
- **HTTP** is a *request → response* conversation. The client asks, the server answers, done.
- A **WebSocket** is a *connection that stays open*. Once it's set up, either side can send a
  message at any time.

## 2. Why WebSockets exist
With plain HTTP, a server can't contact the browser on its own. A chat app would have to ask
"anything new?" every few seconds (**polling**). That's slow (up to one interval of delay) and
wasteful (most answers are "no"). A WebSocket lets the server push a new message the moment it exists.

## 3. How it works, step by step
1. The browser sends a normal HTTP request with the headers `Upgrade: websocket` and `Connection: Upgrade`.
2. The server replies `101 Switching Protocols`. From now on, the same TCP connection carries
   WebSocket **frames** instead of HTTP.
3. Both sides send frames, usually small JSON text strings.
4. Either side can close the connection with a **close code**, for example 1000 for normal,
   or app-defined codes from 4000 to 4999.
5. If the network drops, the connection just dies. The client must notice and **reconnect**.

## 4. Small example (browser JavaScript)
```js
const ws = new WebSocket('wss://example.com/ws/inbox/?token=abc');
ws.onopen    = () => ws.send(JSON.stringify({action: 'ping'}));
ws.onmessage = (e) => console.log('server says', JSON.parse(e.data));
ws.onclose   = (e) => console.log('closed with code', e.code);
```

## 5. In our project
- `assets/app.js` opens **one** socket per logged-in tab: `new WebSocket(.../ws/inbox/?token=...)`.
- The token travels in the URL, because the browser `WebSocket` API can't set an `Authorization` header.
  `chats/middleware.py` reads it. (The audit's SEC-8 notes URLs can end up in logs.)
- **Message types the client sends:** `ping` every 30 s, `message`, and `read`.
- **Message types the server sends:** `pong`, `message`, `read`, and `error`.
- **Close code 4401** (`CLOSE_UNAUTHENTICATED` in `chats/consumers.py`) means "not logged in". The client
  refreshes the token, then reconnects.
- **Other drops:** the client retries after 1 s, 2 s, 4s… capped at 15 s (`ws.onclose` in `app.js`).
- **HTTP still does the rest:** login, chat list, message history, profile.

## 6. Alternatives
| Option | How | When it fits |
|---|---|---|
| Short polling | `setInterval(fetch, 5000)` | Updates rarely matter; simplest possible |
| Long polling | The server holds the request open until there's news | Old proxies that break WebSockets |
| Server-Sent Events (SSE) | One-way server → browser stream over HTTP | Notifications and feeds where the client rarely sends |
| **WebSocket** | Two-way, always open | Chat, games, collaborative editing |

## 7. Common mistakes
- **Forgetting that connections cost resources even when idle.** 10,000 people with the app
  open means 10,000 open sockets, memory and file descriptors, even if nobody types. That's why
  scaling here is measured in *users online*, not registered users.
- **Assuming delivery is guaranteed.** If the socket is down for 5 seconds, anything pushed in
  that window is gone unless the app fetches the gap afterwards (COR-1, task T-09).
- **Reconnecting all at once.** If a server restarts and 5,000 clients retry after exactly 1 s,
  they hit the server together. Adding **jitter** (a random delay) spreads them out (COR-4).
- **Forgetting the `Origin` check.** Without it, any website could open a socket using a
  visitor's credentials. We use `AllowedHostsOriginValidator` in `root/asgi.py`.

## 8. When to use it
Use WebSockets when the server needs to tell the client things **as they happen**, both ways and
often. For a page that updates once a minute, polling or SSE is simpler and cheaper.
