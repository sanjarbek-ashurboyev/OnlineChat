import { $, AVATAR_FALLBACK, state } from './state.js';
import { lastSeenText, timeOf } from './format.js';
import { api } from './api.js';
import { renderChats } from './chats.js';
import { sendRead } from './socket.js';
import { clearComposerIf } from './composer.js';
import { setView } from './nav.js';

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

export function appendMessage(msg) {
  if (state.seenIds.has(msg.id)) return;
  state.seenIds.add(msg.id);
  const rows = $('message-rows');
  const row = messageRow(msg);
  // Rows stay in id order whatever order they arrive in: history, live, catch-up (Codex audit M-09).
  // Search from the bottom, where new messages go.
  let above = rows.lastElementChild;
  while (above && Number(above.dataset.id) > msg.id) above = above.previousElementSibling;
  if (above) above.after(row);
  else rows.prepend(row);
}

export function scrollToBottom() {
  const box = $('messages');
  box.scrollTop = box.scrollHeight;
}

/** `query` is '' for the newest page, or the cursor query for an older one.
 *  Returns null when the user opened another chat (or left) while this was loading. */
async function loadHistory(chatId, query = '') {
  const opened = state.opened;
  const data = await api(`/chats/${chatId}/messages/${query}`);
  if (opened !== state.opened) return null;
  // Newest first from the API; appendMessage puts each row in id order anyway.
  for (const msg of data.results) appendMessage(msg);
  // The newest page holds everything up to its newest message: the catch-up starts there.
  if (!query) state.syncedUpTo = Math.max(0, ...data.results.map((m) => m.id));
  // A cursor link points before the oldest message loaded, so new messages can't shift it (M-11).
  state.olderQuery = data.next ? new URL(data.next).search : null;
  $('load-older').hidden = !state.olderQuery;
  return data;
}

/** Fetch what the open chat got while we weren't listening. It starts from syncedUpTo, which
 *  live messages don't move, so one that never arrived live is fetched too (Codex audit M-03). */
export async function catchUp(chatId) {
  // The history is still loading. Its snapshot may predate the socket, so catch up once it's in.
  if (state.syncedUpTo === null) { state.catchUpDue = true; return; }
  const opened = state.opened;
  const data = await api(`/chats/${chatId}/messages/?after=${state.syncedUpTo}`);
  if (opened !== state.opened) return;             // the user switched chats meanwhile
  if (data.next) { openChat(chatId); return; }     // missed more than a page: reload
  for (const msg of data.results) appendMessage(msg);
  if (data.results.length) {
    state.syncedUpTo = Math.max(state.syncedUpTo, ...data.results.map((m) => m.id));
    scrollToBottom();
  }
}

/** No echo in time (Codex audit H-06). The echo may be what got lost, so look in the history. */
export async function reconcileSend(sent) {
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
  // One request at a time, and the cursor moves only when a page arrives (Codex audit M-10).
  if (state.loadingOlder || !state.olderQuery) return;
  const opened = state.opened;
  const box = $('messages');
  const before = box.scrollHeight;
  state.loadingOlder = true;
  $('load-older').disabled = true;
  try {
    if (!await loadHistory(state.activeId, state.olderQuery)) return;
    box.scrollTop = box.scrollHeight - before;   // keep the reading position
  } catch {
    // The cursor didn't move: the next click asks for the same page.
  } finally {
    if (opened === state.opened) {
      state.loadingOlder = false;
      $('load-older').disabled = false;
    }
  }
});

/* ── open a chat ────────────────────────── */

export async function openChat(chatId) {
  const chat = state.chats.find((c) => c.id === chatId);
  if (!chat) return;

  state.activeId = chatId;
  state.opened += 1;
  state.olderQuery = null;
  state.loadingOlder = false;
  $('load-older').disabled = false;
  state.syncedUpTo = null;
  state.catchUpDue = false;
  state.seenIds.clear();

  setView('chat');
  $('pane-empty').hidden = true;
  $('pane-chat').hidden = false;
  $('message-rows').textContent = '';
  $('send-error').hidden = true;
  showPeer(chat.participant);
  renderChats();

  // Stale: don't draw it, and don't mark a chat read that never reached the screen.
  if (!await loadHistory(chatId)) return;
  scrollToBottom();
  if (state.catchUpDue) { state.catchUpDue = false; catchUp(chatId); }

  // The inbox socket is already open; just clear this chat's unread state.
  sendRead(chatId);
  if (chat.unread_count) { chat.unread_count = 0; renderChats(); }
}

/** The open chat's header. Drawn on opening, and again by every chat list poll (M-13). */
export function showPeer(peer) {
  state.peer = peer;
  $('peer-avatar').src = peer.avatar || AVATAR_FALLBACK;
  $('peer-name').textContent = peer.display_name || 'Unnamed';
  $('peer-status').textContent = lastSeenText(peer);
}

/** Back to the list: the back button, or a swipe that hands over its `velocity`. */
export function leaveChat({ velocity } = {}) {
  setView('list', { velocity });
  state.activeId = null;      // socket stays open — other chats keep updating
  state.opened += 1;
  renderChats();
}

$('back').addEventListener('click', () => leaveChat());
