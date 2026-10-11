# 006 · An open WebSocket's rights end with its token

- **Date:** 2026-10-11 · **Status:** Accepted (chosen by you in session 020)

## Problem
Codex audit H-01: the socket checked the token and `is_active` only when it opened. Access tokens last
5 minutes (SimpleJWT's default), but a socket could stay open for days, so a stolen or expired token,
or a disabled account, kept sending and receiving through a socket that was already open.

## Options considered
1. **Close at token expiry** with 4401; the browser renews its token and reconnects. `app.js` already did this
   for 4401, so no frontend change.
2. **Renew over the socket:** before expiry, the browser sends `{action: 'auth', token}` on the open socket and the
   server extends the deadline. No reconnects, but new code on both sides and a browser test.
3. **Option 1 with 15-minute access tokens:** 3× fewer reconnects, but a stolen token works longer (REST too).

In all three, a separate check every 60 s closes the socket if the account was disabled.

## Chosen: option 1
- The smallest change, and the browser side already existed and was tested (T-09).
- Checked end to end in a real browser (session 020): with a 20 s token, the server closed at 18.6 s with 4401,
  the page renewed its token, reconnected, and a message sent during the gap came back through the gap fetch.
- It also fixes M-02 (group membership expiring after 24 h) for free, together with a 12 h cap for any
  token lifetime.

## Disadvantages and limits
- **Every tab reconnects about every 5 minutes.** At the plan's 10,000 online that's about 33 reconnects a second,
  each with a token check, presence write, group join, `last_seen` write, and a REST gap fetch plus chat-list
  reload. **The load tester doesn't simulate this yet** (its tokens last hours), so its capacity numbers are
  optimistic.
- **A message sent at the instant of the close** can lose its echo. It's saved and comes back through the gap fetch,
  but the text also stays in the composer, so a user could send it twice.
- **Up to 60 s** between disabling an account and its sockets closing. The account check is one indexed query per
  socket per minute (~170/s at 10,000 sockets).

## When another option is better
- **Option 2** once reconnect churn shows up in load tests or users notice the 5-minute blips. It's also the
  natural place for the "socket ticket" from SEC-8 / T-20.
- **Option 3** if 5-minute tokens cause too much refresh traffic overall, not just on sockets.
