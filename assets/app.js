'use strict';

const API = '/api/v1';
const PING_MS = 30000;          // presence keys expire after 90s
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
  activeId: null,
  peer: null,
  ws: null,
  pingTimer: null,
  retry: 0,
  nextPage: 2,
  hasOlder: false,
  seenIds: new Set(),
};

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

async function refreshAccess() {
  if (!state.refresh) return false;
  const res = await fetch(`${API}/auth/token/refresh/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh: state.refresh }),
  });
  if (!res.ok) return false;
  const data = await res.json();
  saveTokens(data.access, data.refresh);
  return true;
}

/* ── api helper ─────────────────────────── */

async function api(path, { method = 'GET', body, isForm = false, retry = true } = {}) {
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
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw Object.assign(new Error('request failed'), { status: res.status, data });
  return data;
}

function errorText(err) {
  if (err.status === 429) return 'Too many searches. Try again later.';
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
  const data = await api('/chats/');
  state.chats = data.results;
  renderChats();
}

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

async function loadHistory(chatId, page = 1) {
  // The API returns newest-first; reverse so the oldest renders at the top.
  const data = await api(`/chats/${chatId}/messages/?page=${page}`);
  const ordered = [...data.results].reverse();
  for (const msg of ordered) appendMessage(msg, { prepend: page > 1 });
  state.hasOlder = Boolean(data.next);
  $('load-older').hidden = !state.hasOlder;
  return data;
}

$('load-older').addEventListener('click', async () => {
  const box = $('messages');
  const before = box.scrollHeight;
  await loadHistory(state.activeId, state.nextPage++);
  box.scrollTop = box.scrollHeight - before;   // keep the reading position
});

/* ── open a chat ────────────────────────── */

async function openChat(chatId) {
  const chat = state.chats.find((c) => c.id === chatId);
  if (!chat) return;

  state.activeId = chatId;
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

  await loadHistory(chatId, 1);
  scrollToBottom();

  // The inbox socket is already open; just clear this chat's unread state.
  sendRead(chatId);
  if (chat.unread_count) { chat.unread_count = 0; renderChats(); }
}

$('back').addEventListener('click', () => {
  $('app').dataset.view = 'list';
  state.activeId = null;      // socket stays open — other chats keep updating
  renderChats();
});

/* ── websocket ──────────────────────────── */

function setConn(cls) {
  $('conn-state').className = 'conn' + (cls ? ' ' + cls : '');
}

function closeSocket() {
  clearInterval(state.pingTimer);
  if (state.ws) {
    state.ws.onclose = null;          // deliberate close: do not reconnect
    state.ws.close();
    state.ws = null;
  }
  setConn('');
}

function socketSend(payload) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return false;
  state.ws.send(JSON.stringify(payload));
  return true;
}

function sendRead(chatId) {
  socketSend({ action: 'read', chat_id: chatId });
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

  ws.onopen = () => {
    state.retry = 0;
    setConn('is-open');
    if (state.activeId) sendRead(state.activeId);
    state.pingTimer = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ action: 'ping' }));
    }, PING_MS);
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.type === 'message') {
      if (data.chat_id === state.activeId) {
        const box = $('messages');
        const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
        appendMessage(data);
        if (atBottom) scrollToBottom();
        if (data.sender_id !== state.me.id) sendRead(data.chat_id);
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
      if (data.chat_id === state.activeId) {
        document.querySelectorAll('#message-rows .row.out .meta').forEach((el) => {
          if (el.textContent.endsWith(' ✓')) el.textContent += '✓';
        });
      }
      return;
    }

    if (data.type === 'error') {
      $('send-error').textContent = data.detail;
      $('send-error').hidden = false;
    }
  };

  ws.onclose = (event) => {
    clearInterval(state.pingTimer);
    setConn('is-down');
    if (!state.me) return;                   // logged out on purpose

    // 4401 means the token expired mid-session: renew, then reconnect.
    if (event.code === 4401) {
      refreshAccess().then((ok) => (ok ? connectInbox() : logout()));
      return;
    }

    const delay = Math.min(1000 * 2 ** state.retry++, 15000);
    setTimeout(() => { if (state.me) connectInbox(); }, delay);
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

$('send-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const text = composer.value.trim();
  if (!text) return;

  if (!socketSend({ action: 'message', chat_id: state.activeId, text })) {
    $('send-error').textContent = 'Not connected. Reconnecting…';
    $('send-error').hidden = false;
    return;
  }

  composer.value = '';
  composer.style.height = 'auto';
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
  closeSocket();
  clearTokens();
  state.me = null;
  state.chats = [];
  state.activeId = null;
  $('app').hidden = true;
  $('auth').hidden = false;
}

$('logout').addEventListener('click', logout);

async function start() {
  try {
    state.me = await api('/auth/profile/');
  } catch {
    logout();
    return;
  }
  $('auth').hidden = true;
  $('app').hidden = false;
  $('app').dataset.view = 'list';
  renderMe();
  await loadChats();
  connectInbox();          // one socket for every conversation
}

// Messages arrive over the socket; this poll only refreshes other people's
// online dots, which nothing pushes to us.
setInterval(() => { if (state.me) loadChats(); }, 45000);

if (state.access) start();
