import { $, state } from './state.js';
import { shortDate } from './format.js';
import { avatarSrc } from './avatar.js';
import { createSpring } from './motion.js';
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

/* Rows are kept between draws, one per chat id: a row that changes place can glide there, and a focused row keeps
   the keyboard's focus. Each holds its elements, and a spring for its glide once it has moved. */
const rows = new Map();

function makeRow(chatId) {
  const part = (tag, className) => Object.assign(document.createElement(tag), { className });
  const row = {
    li: document.createElement('li'),
    btn: part('button', 'chat-row'),
    img: part('img', 'avatar'),
    dot: part('span', 'dot'),
    name: part('span', 'chat-name'),
    time: part('span', 'chat-time'),
    preview: part('span', 'chat-preview'),
    badge: part('span', 'badge'),
    glide: null,
  };
  row.img.alt = '';
  row.btn.addEventListener('click', () => openChat(chatId));
  const wrap = part('div', 'avatar-wrap');
  wrap.append(row.img, row.dot);
  const main = part('div', 'chat-main');
  main.append(row.name, row.time, row.preview);
  row.btn.append(wrap, main);
  row.li.append(row.btn);
  return row;
}

function fillRow(row, chat) {
  const p = chat.participant;
  const active = chat.id === state.activeId;
  row.btn.classList.toggle('is-active', active);
  if (active) row.btn.setAttribute('aria-current', 'true');
  else row.btn.removeAttribute('aria-current');
  const src = avatarSrc(p);
  if (row.img.getAttribute('src') !== src) row.img.src = src;
  row.dot.hidden = !p.is_online;        // only "online" gets a dot; the chat's header says it in words
  row.name.textContent = p.display_name || 'Unnamed';
  row.time.textContent = chat.last_message ? shortDate(chat.last_message.created_at) : '';
  row.preview.textContent = chat.last_message ? chat.last_message.text : 'No messages yet';
  if (chat.unread_count > 0) {
    row.badge.textContent = chat.unread_count;
    row.preview.after(row.badge);
  } else {
    row.badge.remove();
  }
}

/** Slide a row from `offset` px away (where it was on screen) to its place. */
function glide(row, offset) {
  row.glide ??= createSpring((y) => {
    row.li.style.transform = y ? `translateY(${y}px)` : '';
    row.li.style.zIndex = y > 0 ? '1' : '';    // a row rising to the top passes over the ones making room
  }, { response: 0.4 });
  row.glide.jump(offset);
  row.glide.to(0);
}

const filterField = $('lookup-form').elements.query;

/** Typing in the search field shows only the loaded chats whose name contains it. */
function matchesFilter(chat) {
  const query = filterField.value.trim().toLocaleLowerCase();
  return !query || (chat.participant.display_name || '').toLocaleLowerCase().includes(query);
}

/** Draw the list from state.chats. Rows that changed place glide there from where they are on screen now, even
 *  halfway through an earlier glide; `glide: false` puts them in place at once (filtering, signing out). */
export function renderChats({ glide: animate = true } = {}) {
  const list = $('chat-list');
  // Where each row is on screen now: its place in the layout (offsetTop ignores transforms), plus its glide.
  const wasAt = new Map();
  for (const [id, row] of rows) if (!row.li.hidden) wasAt.set(id, row.li.offsetTop + (row.glide?.value ?? 0));
  const focused = list.contains(document.activeElement) ? document.activeElement : null;

  // Moving a node takes focus off it, so only the rows out of place are moved.
  const keep = new Set();
  let next = list.firstElementChild;
  for (const chat of state.chats) {
    if (!rows.has(chat.id)) rows.set(chat.id, makeRow(chat.id));
    const row = rows.get(chat.id);
    fillRow(row, chat);
    row.li.hidden = !matchesFilter(chat);
    keep.add(chat.id);
    if (row.li === next) next = next.nextElementSibling;
    else list.insertBefore(row.li, next);
  }
  for (const [id, row] of rows) {
    if (keep.has(id)) continue;
    row.glide?.jump(0);
    row.li.remove();
    rows.delete(id);
  }
  if (focused?.isConnected && document.activeElement !== focused) focused.focus({ preventScroll: true });

  for (const [id, row] of rows) {
    if (row.li.hidden || !wasAt.has(id)) continue;      // a row just shown or added appears in place
    const offset = wasAt.get(id) - row.li.offsetTop;
    if (animate && Math.abs(offset) >= 0.5) glide(row, offset);
    else row.glide?.jump(0);
  }

  const query = filterField.value.trim();
  const shown = state.chats.filter(matchesFilter).length;
  $('chat-empty').hidden = state.chats.length > 0;
  $('filter-empty').hidden = !state.chats.length || shown > 0;
  $('filter-empty').textContent = /^\+?[\d\s()-]+$/.test(query)
    ? 'No chats match. To find this number, press Search.'
    : `No chats match “${query}”.`;
}

filterField.addEventListener('input', () => renderChats({ glide: false }));
filterField.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !filterField.value) return;
  filterField.value = '';
  renderChats({ glide: false });
});

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
    renderChats({ glide: false });     // the field doubles as the filter: show every chat again
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
