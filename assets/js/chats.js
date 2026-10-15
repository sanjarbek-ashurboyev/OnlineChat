import { $, AVATAR_FALLBACK, state } from './state.js';
import { shortDate } from './format.js';
import { api, errorText } from './api.js';
import { openChat, showPeer } from './messages.js';
import { showReadUpTo } from './socket.js';

/* ── chat list ──────────────────────────── */

export async function loadChats() {
  const pageCount = state.chatPages;
  const pages = await Promise.all(Array.from({ length: pageCount }, async (_, i) => {
    try {
      return await api(i ? `/chats/?page=${i + 1}` : '/chats/');
    } catch (err) {
      if (i && err.status === 404) return null;  // a deleted chat can remove the last page
      throw err;
    }
  }));
  const validPages = [];
  for (const page of pages) {
    if (!page) break;
    validPages.push(page);
    if (!page.next) break;
  }
  // Numbered pages can overlap while live messages reorder the list. Keep one row per id.
  const refreshed = new Map(validPages.flatMap((page) => page.results).map((chat) => [chat.id, chat]));
  const outside = state.chats.filter((chat) => !refreshed.has(chat.id));
  const outsideIds = new Set(outside.map((chat) => chat.id));
  // A lookup can open a chat beyond the loaded pages. Refresh it through the same privacy rules.
  const extraPages = await Promise.all([...outsideIds].map((id) => api(`/chats/?chat_id=${id}`)));
  for (const page of extraPages) {
    for (const chat of page.results) refreshed.set(chat.id, chat);
  }
  // Preserve chats added by "Show more" or a lookup while these requests were pending.
  // Missing targeted results are deleted chats, so their old cached rows are removed.
  for (const chat of state.chats) {
    if (!refreshed.has(chat.id) && !outsideIds.has(chat.id)) refreshed.set(chat.id, chat);
  }
  state.chats = [...refreshed.values()];
  if (pageCount === state.chatPages) {
    state.chatPages = validPages.length;
    $('more-chats').hidden = validPages.length < pageCount || !validPages[validPages.length - 1].next;
  }
  renderChats();
  const active = refreshed.get(state.activeId);
  if (!active) return;
  showPeer(active.participant);
  if (active.peer_read_up_to) showReadUpTo(active.peer_read_up_to);
}

$('more-chats').addEventListener('click', async () => {
  // One request at a time: two clicks used to fetch the same page and skip the next (Codex audit M-10).
  if (state.loadingMoreChats) return;
  state.loadingMoreChats = true;
  $('more-chats').disabled = true;
  try {
    const data = await api(`/chats/?page=${state.chatPages + 1}`);
    state.chatPages += 1;              // only once the page has arrived
    const known = new Set(state.chats.map((c) => c.id));
    state.chats.push(...data.results.filter((c) => !known.has(c.id)));
    $('more-chats').hidden = !data.next;
    renderChats();
  } catch {
    // Nothing moved: the next click asks for the same page.
  } finally {
    state.loadingMoreChats = false;
    $('more-chats').disabled = false;
  }
});

export function renderChats() {
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
    const chat = await api('/chats/', { method: 'POST', body: { phone_number: field.value.trim() } });
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
