import { $, PING_MS, PONG_GRACE_MS, state } from './state.js';
import { refreshAccess } from './tokens.js';
import { loadChats, renderChats } from './chats.js';
import { appendMessage, catchUp, noteUnseen, scrollToBottom, setStatus, settleOutbox } from './messages.js';
import { clearComposerIf, failSend, isOurSend, settleSend } from './composer.js';
import { signOut } from './session.js';

/* ── websocket ──────────────────────────── */

let connClass = '';

/** The connection in words, where Telegram puts it: the list's title, and the open chat's status line.
 *  Not by colour alone: a red or green dot says nothing to someone who can't tell them apart. */
function setConn(cls) {
  connClass = cls;
  const open = cls === 'is-open';
  const words = open ? 'Chats' : navigator.onLine ? 'Connecting…' : 'Waiting for network…';
  $('conn-state').className = 'conn' + (cls ? ' ' + cls : '');
  $('conn-state').textContent = words;
  $('peer-conn').textContent = open ? '' : words;
  $('peer-conn').hidden = open;
  $('peer-status').hidden = !open;
}

window.addEventListener('offline', () => setConn(connClass));
// Back online: try now, instead of waiting out a backoff that grew while the network was gone.
window.addEventListener('online', () => {
  setConn(connClass);
  if (state.me && connClass !== 'is-open') {
    state.retry = 0;
    connectInbox();
  }
});

export function closeSocket() {
  clearInterval(state.pingTimer);
  clearTimeout(state.reconnectTimer);
  if (state.ws) {
    // Deliberate close: detach every handler, so nothing from this socket runs again.
    state.ws.onopen = state.ws.onmessage = state.ws.onclose = null;
    state.ws.close();
    state.ws = null;
  }
  setConn('');
}

/** Full jitter: a random wait up to the backoff, so after a restart every client
 *  doesn't reconnect in the same instant (COR-4). */
function scheduleReconnect() {
  const delay = Math.random() * Math.min(1000 * 2 ** state.retry++, 15000);
  clearTimeout(state.reconnectTimer);
  state.reconnectTimer = setTimeout(connectInbox, delay);
}

export function socketSend(payload) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return false;
  state.ws.send(JSON.stringify(payload));
  return true;
}

export function sendRead(chatId) {
  // Only up to the newest message on screen: one still on its way stays unread (Codex audit M-06).
  if (chatId !== state.activeId || !state.seenIds.size) return;
  socketSend({ action: 'read', chat_id: chatId, up_to: Math.max(...state.seenIds) });
}

/** The other person has read our messages up to this id: two ticks on those. */
export function showReadUpTo(upTo) {
  document.querySelectorAll('#message-rows .row.out[data-status="sent"]').forEach((row) => {
    if (Number(row.dataset.id) <= upTo) setStatus(row, 'read');
  });
}

/** A message arrived for a chat that isn't on screen: update its sidebar row. */
function applyToSidebar(msg) {
  const chat = state.chats.find((c) => c.id === msg.chat_id);
  if (!chat) {
    loadChats();                       // a conversation someone else just started
    return;
  }
  chat.last_message = { text: msg.text, created_at: msg.created_at };
  const isActive = msg.chat_id === state.activeId;
  if (!isActive && msg.sender_id !== state.me.id) {
    chat.unread_count = (chat.unread_count || 0) + 1;
  }
  // Newest conversation first, matching the server's ordering.
  state.chats = [chat, ...state.chats.filter((c) => c.id !== chat.id)];
  renderChats();
}

export function connectInbox() {
  closeSocket();
  if (!state.access) return;

  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(
    `${scheme}://${location.host}/ws/inbox/?token=${encodeURIComponent(state.access)}`);
  state.ws = ws;

  // A refused socket (4401, 4429) is accepted and then closed, so onopen alone doesn't
  // mean we're in. The first frame from the server does: ping on open to get one.
  let ready = false;
  const onReady = () => {
    ready = true;
    state.retry = 0;
    setConn('is-open');
    // The socket doesn't replay what it missed while down, or before it first connected;
    // Postgres has it (COR-1, Codex audit M-03). So on every connect, not just reconnects.
    if (state.activeId) catchUp(state.activeId);
    loadChats().catch(() => {});
    if (state.activeId) sendRead(state.activeId);
  };

  ws.onopen = () => {
    state.lastFrameAt = Date.now();
    ws.send(JSON.stringify({ action: 'ping' }));
    state.pingTimer = setInterval(() => {
      // The last ping got no answer: the connection is dead even if the browser hasn't noticed.
      if (Date.now() - state.lastFrameAt > PING_MS + PONG_GRACE_MS) {
        closeSocket();
        failSend();
        setConn('is-down');
        scheduleReconnect();
        return;
      }
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ action: 'ping' }));
    }, PING_MS);
  };

  ws.onmessage = (event) => {
    state.lastFrameAt = Date.now();
    const data = JSON.parse(event.data);
    if (!ready) onReady();
    if (data.type === 'pong') return;

    if (data.type === 'message') {
      if (data.chat_id === state.activeId) {
        const box = $('messages');
        const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
        appendMessage(data);
        if (atBottom) scrollToBottom();
        else if (data.sender_id !== state.me.id) noteUnseen();
        if (data.sender_id !== state.me.id) sendRead(data.chat_id);
      } else {
        settleOutbox(data, data.chat_id);    // the open chat's is settled by appendMessage
      }
      if (isOurSend(data)) {
        clearComposerIf(data.text);
        settleSend();
      }
      applyToSidebar(data);
      return;
    }

    if (data.type === 'read') {
      if (data.by === state.me.id) {
        // Our own read landed: clear that badge without refetching.
        const chat = state.chats.find((c) => c.id === data.chat_id);
        if (chat && chat.unread_count) { chat.unread_count = 0; renderChats(); }
        return;
      }
      if (data.chat_id === state.activeId) showReadUpTo(data.up_to);
      return;
    }

    if (data.type === 'error') {
      // Errors don't say which frame they answer, so any error fails a waiting send: its bubble says
      // "Not delivered" and its text goes back to the composer. If it was saved after all, its echo or the
      // next catch-up replaces the bubble.
      failSend();
      $('send-error').textContent = data.detail;
      $('send-error').hidden = false;
    }
  };

  ws.onclose = (event) => {
    clearInterval(state.pingTimer);
    failSend();                              // no answer coming; a catch-up replaces it if it was saved
    setConn('is-down');
    if (!state.me) return;                   // logged out on purpose

    // 4401 means the token expired mid-session: renew, then reconnect. Through the
    // backoff too, so a token the server keeps refusing can't cause a tight loop.
    // Only a refused refresh token signs out; a network error just tries again (M-12).
    if (event.code === 4401) {
      refreshAccess().then((ok) => (ok ? scheduleReconnect() : signOut()), scheduleReconnect);
      return;
    }
    scheduleReconnect();
  };
}
