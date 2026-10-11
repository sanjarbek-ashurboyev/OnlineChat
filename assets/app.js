'use strict';

const API = '/api/v1';
const PING_MS = 30000;          // presence keys expire after 90s
const PONG_GRACE_MS = 10000;    // no frame for PING_MS + this: the connection is dead (Codex audit H-06)
const ACK_TIMEOUT_MS = 10000;   // no echo by then: look in the history (Codex audit H-06)
const START_RETRY_MS = 5000;    // the server couldn't be reached at startup (Codex audit M-12)
const AVATAR_FALLBACK =
  'data:image/svg+xml;utf8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">' +
    '<rect width="40" height="40" fill="#c9ced6"/>' +
    '<circle cx="20" cy="15" r="7" fill="#fff"/>' +
    '<path d="M6 40c0-8 6.5-13 14-13s14 5 14 13z" fill="#fff"/></svg>');

const $ = (id) => document.getElementById(id);

const state = {
  access: localStorage.getItem('access'),
  refresh: localStorage.getItem('refresh'),
  me: null,
  chats: [],
  chatPages: 1,
  activeId: null,
  opened: 0,              // bumped by every openChat; an answer for an earlier one is dropped
  sending: null,          // { chatId, text } of the message waiting for the server's answer
  peer: null,
  ws: null,
  pingTimer: null,
  retry: 0,
  nextPage: 2,
  hasOlder: false,
  seenIds: new Set(),
  session: 0,             // bumped by logout; answers for an earlier session are dropped (Codex audit H-04)
  reconnectTimer: null,
  ackTimer: null,
  startTimer: null,
  lastFrameAt: 0,
};

/** A promise that never settles. Returned for an answer from an earlier session, so whatever
 *  the caller does next (draw chats, save tokens, show an error) never runs. */
const dropped = () => new Promise(() => {});

/* ── tokens ─────────────────────────────── */

function saveTokens(access, refresh) {
  state.access = access;
  localStorage.setItem('access', access);
  if (refresh) {
    state.refresh = refresh;
    localStorage.setItem('refresh', refresh);
  }
}

function clearTokens() {
  state.access = state.refresh = null;
  localStorage.removeItem('access');
  localStorage.removeItem('refresh');
}

/** true: renewed. false: the server refused the refresh token, so sign in again.
 *  Throws on a network or server error, which is no reason to sign out (Codex audit M-12). */
async function refreshAccess() {
  if (!state.refresh) return false;
  const session = state.session;
  const res = await fetch(`${API}/auth/token/refresh/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh: state.refresh }),
  });
  if (res.status === 400 || res.status === 401) return session === state.session ? false : dropped();
  if (!res.ok) throw Object.assign(new Error('refresh failed'), { status: res.status });
  const data = await res.json();
  // Signed out meanwhile: these tokens must not sign anyone back in.
  if (session !== state.session) return dropped();
  saveTokens(data.access, data.refresh);
  return true;
}

/* ── api helper ─────────────────────────── */

async function api(path, { method = 'GET', body, isForm = false, retry = true } = {}) {
  const session = state.session;
  const headers = {};
  if (state.access) headers.Authorization = `Bearer ${state.access}`;
  if (body && !isForm) headers['Content-Type'] = 'application/json';

  const res = await fetch(API + path, {
    method,
    headers,
    body: isForm ? body : (body ? JSON.stringify(body) : undefined),
  });

  // Access tokens last 5 minutes; renew once and replay rather than logging out.
  if (res.status === 401 && retry && await refreshAccess()) {
    return api(path, { method, body, isForm, retry: false });
  }

  const text = await res.text();
  if (session !== state.session) return dropped();   // an answer for whoever was signed in before
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw Object.assign(new Error('request failed'), { status: res.status, data });
  return data;
}

function errorText(err) {
  // A 429's detail is the server's own "Expected available in N seconds" (Codex audit L-03).
  const d = err.data;
  if (!d) return 'Something went wrong.';
  if (typeof d === 'string') return d;
  if (d.detail) return d.detail;
  return Object.values(d)
    .map((v) => (Array.isArray(v) ? v.join(' ') : v))
    .join('\n');
}

/* ── formatting ─────────────────────────── */

const timeOf = (iso) =>
  new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

function shortDate(iso) {
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay ? timeOf(iso) : d.toLocaleDateString([], { day: 'numeric', month: 'short' });
}

function lastSeenText(user) {
  if (user.is_online) return 'online';
  if (!user.last_seen) return 'offline';
  return `last seen ${shortDate(user.last_seen)}`;
}

/* ── auth screen ────────────────────────── */

let authMode = 'login';

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    authMode = tab.dataset.mode;
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('is-active', t === tab));
    document.querySelectorAll('.only-register').forEach((el) => {
      el.hidden = authMode !== 'register';
      el.querySelectorAll('input').forEach((i) => { i.required = authMode === 'register'; });
    });
    $('auth-submit').textContent = authMode === 'login' ? 'Log in' : 'Create account';
    $('auth-error').hidden = true;
  });
});

$('auth-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const phone = form.get('phone_number').trim();
  const password = form.get('password');
  const btn = $('auth-submit');
  btn.disabled = true;
  $('auth-error').hidden = true;

  try {
    if (authMode === 'register') {
      await api('/auth/register/', {
        method: 'POST',
        body: {
          phone_number: phone,
          password,
          confirm_password: form.get('confirm_password'),
          first_name: form.get('first_name') || '',
        },
      });
    }
    const tokens = await api('/auth/login/', {
      method: 'POST',
      body: { phone_number: phone, password },
    });
    saveTokens(tokens.access, tokens.refresh);
    e.target.reset();
    await start();
  } catch (err) {
    $('auth-error').textContent = errorText(err);
    $('auth-error').hidden = false;
  } finally {
    btn.disabled = false;
  }
});

/* ── chat list ──────────────────────────── */

async function loadChats() {
  // Page 1 holds the newest conversations. Keep the older pages already shown below it.
  const data = await api('/chats/');
  const fresh = new Set(data.results.map((c) => c.id));
  state.chats = [...data.results, ...state.chats.filter((c) => !fresh.has(c.id))];
  if (state.chatPages === 1) $('more-chats').hidden = !data.next;
  renderChats();
  // Receipts sent while our socket was down never arrive; the list says how far they got (M-08).
  const active = data.results.find((c) => c.id === state.activeId);
  if (active && active.peer_read_up_to) showReadUpTo(active.peer_read_up_to);
}

$('more-chats').addEventListener('click', async () => {
  const data = await api(`/chats/?page=${state.chatPages + 1}`);
  state.chatPages += 1;
  const known = new Set(state.chats.map((c) => c.id));
  state.chats.push(...data.results.filter((c) => !known.has(c.id)));
  $('more-chats').hidden = !data.next;
  renderChats();
});

function renderChats() {
  const list = $('chat-list');
  list.textContent = '';
  $('chat-empty').hidden = state.chats.length > 0;

  for (const chat of state.chats) {
    const p = chat.participant;

    const li = document.createElement('li');
    const btn = document.createElement('button');
    btn.className = 'chat-row' + (chat.id === state.activeId ? ' is-active' : '');
    btn.addEventListener('click', () => openChat(chat.id));

    const wrap = document.createElement('div');
    wrap.className = 'avatar-wrap';
    const img = document.createElement('img');
    img.className = 'avatar';
    img.src = p.avatar || AVATAR_FALLBACK;
    img.alt = '';
    const dot = document.createElement('span');
    dot.className = 'dot' + (p.is_online ? ' is-online' : '');
    wrap.append(img, dot);

    const main = document.createElement('div');
    main.className = 'chat-main';

    const top = document.createElement('div');
    top.className = 'chat-top';
    const name = document.createElement('span');
    name.className = 'chat-name';
    name.textContent = p.display_name || 'Unnamed';
    const time = document.createElement('span');
    time.className = 'chat-time';
    time.textContent = chat.last_message ? shortDate(chat.last_message.created_at) : '';
    top.append(name, time);

    const preview = document.createElement('div');
    preview.className = 'chat-preview';
    preview.textContent = chat.last_message ? chat.last_message.text : 'No messages yet';
    if (chat.unread_count > 0) {
      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.textContent = chat.unread_count;
      preview.append(badge);
    }

    main.append(top, preview);
    btn.append(wrap, main);
    li.append(btn);
    list.append(li);
  }
}

/* ── lookup ─────────────────────────────── */

$('lookup-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const field = e.target.querySelector('input');
  const msg = $('lookup-msg');
  msg.hidden = false;
  msg.textContent = 'Searching…';

  try {
    const user = await api(`/users/lookup/?phone_number=${encodeURIComponent(field.value.trim())}`);
    const chat = await api('/chats/', { method: 'POST', body: { participant_id: user.id } });
    field.value = '';
    msg.hidden = true;
    await loadChats();
    // An old conversation may be on a page that isn't loaded yet.
    if (!state.chats.some((c) => c.id === chat.id)) state.chats.push(chat);
    openChat(chat.id);
  } catch (err) {
    msg.textContent = err.status === 404
      ? 'Nobody is registered with that number.'
      : errorText(err);
  }
});

/* ── messages ───────────────────────────── */

function messageRow(msg) {
  const mine = msg.sender_id === state.me.id;
  const row = document.createElement('div');
  row.className = 'row ' + (mine ? 'out' : 'in');
  row.dataset.id = msg.id;

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = msg.text;          // textContent, never innerHTML

  const meta = document.createElement('span');
  meta.className = 'meta';
  meta.textContent = timeOf(msg.created_at) + (mine ? (msg.is_read ? ' ✓✓' : ' ✓') : '');
  bubble.append(meta);

  row.append(bubble);
  return row;
}

function appendMessage(msg, { prepend = false } = {}) {
  if (state.seenIds.has(msg.id)) return;
  state.seenIds.add(msg.id);
  const rows = $('message-rows');
  const row = messageRow(msg);
  if (prepend) rows.prepend(row);
  else rows.append(row);
}

function scrollToBottom() {
  const box = $('messages');
  box.scrollTop = box.scrollHeight;
}

/** Returns null when the user opened another chat (or left) while this was loading. */
async function loadHistory(chatId, page = 1) {
  const opened = state.opened;
  const data = await api(`/chats/${chatId}/messages/?page=${page}`);
  if (opened !== state.opened) return null;
  // The API returns newest first. Page 1 is appended, so reverse it: oldest at the top.
  // Older pages are prepended one at a time, so keep newest first: each lands above the last.
  const ordered = page > 1 ? data.results : [...data.results].reverse();
  for (const msg of ordered) appendMessage(msg, { prepend: page > 1 });
  state.hasOlder = Boolean(data.next);
  $('load-older').hidden = !state.hasOlder;
  return data;
}

/** Append what arrived in the open chat while the socket was down. */
async function catchUp(chatId) {
  const after = Math.max(0, ...state.seenIds);
  const data = await api(`/chats/${chatId}/messages/?after=${after}`);
  if (chatId !== state.activeId) return;           // the user switched chats meanwhile
  if (data.next) { openChat(chatId); return; }     // missed more than a page: reload
  for (const msg of data.results) appendMessage(msg);
  if (data.results.length) scrollToBottom();
}

/** No echo in time (Codex audit H-06). The echo may be what got lost, so look in the history. */
async function reconcileSend(sent) {
  let saved = false;
  try {
    const data = await api(`/chats/${sent.chatId}/messages/?after=${sent.after}`);
    saved = data.results.some((m) => m.sender_id === state.me.id && m.text === sent.text);
  } catch {
    // Can't tell: say so below, and keep the text.
  }
  if (saved) {
    clearComposerIf(sent.text);
    if (sent.chatId === state.activeId) catchUp(sent.chatId);   // draw it
    return;
  }
  $('send-error').textContent = "The server didn't answer. Your message may not have been sent.";
  $('send-error').hidden = false;
}

$('load-older').addEventListener('click', async () => {
  const box = $('messages');
  const before = box.scrollHeight;
  if (!await loadHistory(state.activeId, state.nextPage++)) return;
  box.scrollTop = box.scrollHeight - before;   // keep the reading position
});

/* ── open a chat ────────────────────────── */

async function openChat(chatId) {
  const chat = state.chats.find((c) => c.id === chatId);
  if (!chat) return;

  state.activeId = chatId;
  state.opened += 1;
  state.peer = chat.participant;
  state.nextPage = 2;
  state.seenIds.clear();

  $('app').dataset.view = 'chat';
  $('pane-empty').hidden = true;
  $('pane-chat').hidden = false;
  $('message-rows').textContent = '';
  $('send-error').hidden = true;
  $('peer-avatar').src = chat.participant.avatar || AVATAR_FALLBACK;
  $('peer-name').textContent = chat.participant.display_name || 'Unnamed';
  $('peer-status').textContent = lastSeenText(chat.participant);
  renderChats();

  // Stale: don't draw it, and don't mark a chat read that never reached the screen.
  if (!await loadHistory(chatId, 1)) return;
  scrollToBottom();

  // The inbox socket is already open; just clear this chat's unread state.
  sendRead(chatId);
  if (chat.unread_count) { chat.unread_count = 0; renderChats(); }
}

$('back').addEventListener('click', () => {
  $('app').dataset.view = 'list';
  state.activeId = null;      // socket stays open — other chats keep updating
  state.opened += 1;
  renderChats();
});

/* ── websocket ──────────────────────────── */

function setConn(cls) {
  $('conn-state').className = 'conn' + (cls ? ' ' + cls : '');
}

function closeSocket() {
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

function socketSend(payload) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return false;
  state.ws.send(JSON.stringify(payload));
  return true;
}

function sendRead(chatId) {
  // Only up to the newest message on screen: one still on its way stays unread (Codex audit M-06).
  if (chatId !== state.activeId || !state.seenIds.size) return;
  socketSend({ action: 'read', chat_id: chatId, up_to: Math.max(...state.seenIds) });
}

/** The other person has read our messages up to this id: show ✓✓ on those. */
function showReadUpTo(upTo) {
  document.querySelectorAll('#message-rows .row.out').forEach((row) => {
    const meta = row.querySelector('.meta');
    if (Number(row.dataset.id) <= upTo && meta.textContent.endsWith(' ✓')) meta.textContent += '✓';
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

function connectInbox() {
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
    const reconnected = state.retry > 0;
    state.retry = 0;
    setConn('is-open');
    // The socket doesn't replay what it missed while down; Postgres has it (COR-1).
    if (reconnected) {
      if (state.activeId) catchUp(state.activeId);
      loadChats();
    }
    if (state.activeId) sendRead(state.activeId);
  };

  ws.onopen = () => {
    state.lastFrameAt = Date.now();
    ws.send(JSON.stringify({ action: 'ping' }));
    state.pingTimer = setInterval(() => {
      // The last ping got no answer: the connection is dead even if the browser hasn't noticed.
      if (Date.now() - state.lastFrameAt > PING_MS + PONG_GRACE_MS) {
        closeSocket();
        settleSend();
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
        if (data.sender_id !== state.me.id) sendRead(data.chat_id);
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
      // Errors don't say which frame they answer, so any error fails a waiting send.
      // Its text stays in the composer for a retry.
      settleSend();
      $('send-error').textContent = data.detail;
      $('send-error').hidden = false;
    }
  };

  ws.onclose = (event) => {
    clearInterval(state.pingTimer);
    settleSend();                            // no answer coming; the text stays in the composer
    setConn('is-down');
    if (!state.me) return;                   // logged out on purpose

    // 4401 means the token expired mid-session: renew, then reconnect. Through the
    // backoff too, so a token the server keeps refusing can't cause a tight loop.
    // Only a refused refresh token signs out; a network error just tries again (M-12).
    if (event.code === 4401) {
      refreshAccess().then((ok) => (ok ? scheduleReconnect() : logout()), scheduleReconnect);
      return;
    }
    scheduleReconnect();
  };
}

/* ── composer ───────────────────────────── */

const composer = $('composer-input');

composer.addEventListener('input', () => {
  composer.style.height = 'auto';
  composer.style.height = Math.min(composer.scrollHeight, 140) + 'px';
});

composer.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    $('send-form').requestSubmit();
  }
});

function clearComposerIf(text) {
  if (composer.value.trim() === text) { composer.value = ''; composer.style.height = 'auto'; }
}

/** Stop waiting for the server's answer to our send. */
function settleSend() {
  state.sending = null;
  clearTimeout(state.ackTimer);
}

/** Our own message coming back from the server: the send we're waiting for succeeded. */
function isOurSend(msg) {
  const s = state.sending;
  return Boolean(s) && msg.sender_id === state.me.id && msg.chat_id === s.chatId && msg.text === s.text;
}

$('send-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const text = composer.value.trim();
  if (!text || state.sending) return;     // one message in flight at a time

  if (!socketSend({ action: 'message', chat_id: state.activeId, text })) {
    $('send-error').textContent = 'Not connected. Reconnecting…';
    $('send-error').hidden = false;
    return;
  }

  // Keep the text until the server answers: the echo clears it, an error leaves it.
  // `after` marks where to look in the history if the answer never comes.
  const sent = { chatId: state.activeId, text, after: Math.max(0, ...state.seenIds) };
  state.sending = sent;
  state.ackTimer = setTimeout(() => {
    if (state.sending !== sent) return;
    settleSend();
    reconcileSend(sent);
  }, ACK_TIMEOUT_MS);
  $('send-error').hidden = true;
});

/* ── profile ────────────────────────────── */

$('open-profile').addEventListener('click', () => {
  $('profile-form').first_name.value = state.me.first_name || '';
  $('profile-error').hidden = true;
  $('profile-dialog').showModal();
});

$('profile-cancel').addEventListener('click', () => $('profile-dialog').close());

$('profile-save').addEventListener('click', async () => {
  const form = $('profile-form');
  const body = new FormData();
  body.append('first_name', form.first_name.value);
  if (form.avatar.files[0]) body.append('avatar', form.avatar.files[0]);

  try {
    state.me = await api('/auth/profile/', { method: 'PATCH', body, isForm: true });
    renderMe();
    await loadChats();
    $('profile-dialog').close();
  } catch (err) {
    $('profile-error').textContent = errorText(err);
    $('profile-error').hidden = false;
  }
});

/* ── session ────────────────────────────── */

function renderMe() {
  $('me-avatar').src = state.me.avatar || AVATAR_FALLBACK;
  $('me-name').textContent = state.me.first_name || 'You';
  $('me-phone').textContent = state.me.phone_number;
}

function logout() {
  // Nothing from this session may touch the next one (Codex audit H-04): requests and token
  // refreshes still in flight are dropped, and the socket's handlers and timers are gone.
  state.session += 1;
  closeSocket();
  clearTimeout(state.startTimer);
  settleSend();
  clearTokens();
  state.me = null;
  state.chats = [];
  state.chatPages = 1;
  state.activeId = null;
  state.opened += 1;
  state.peer = null;
  state.retry = 0;
  state.seenIds.clear();
  $('chat-list').textContent = '';
  $('message-rows').textContent = '';
  composer.value = '';
  $('send-error').hidden = true;
  $('lookup-msg').hidden = true;
  $('pane-chat').hidden = true;
  $('pane-empty').hidden = false;
  $('app').hidden = true;
  $('auth').hidden = false;
}

$('logout').addEventListener('click', logout);

async function start() {
  clearTimeout(state.startTimer);   // a manual login while a retry was waiting
  try {
    state.me = await api('/auth/profile/');
  } catch (err) {
    // Only the server refusing our tokens signs us out. A network or server error is
    // retried, keeping the tokens (Codex audit M-12).
    if (err.status === 401) {
      logout();
      return;
    }
    $('auth-error').textContent = "Can't reach the server. Trying again…";
    $('auth-error').hidden = false;
    state.startTimer = setTimeout(start, START_RETRY_MS);
    return;
  }
  $('auth-error').hidden = true;
  $('auth').hidden = true;
  $('app').hidden = false;
  $('app').dataset.view = 'list';
  renderMe();
  // The socket doesn't need the chat list, so a failed list must not keep it closed (M-12).
  connectInbox();          // one socket for every conversation
  loadChats().catch(() => {});   // the poll below tries again
}

// Messages arrive over the socket; this poll only refreshes other people's
// online dots, which nothing pushes to us.
setInterval(() => { if (state.me) loadChats().catch(() => {}); }, 45000);

if (state.access) start();
