import { $, state } from './state.js';
import { avatarSrc } from './avatar.js';
import { dayLabel, lastSeenText, timeOf } from './format.js';
import { api } from './api.js';
import { renderChats } from './chats.js';
import { sendRead } from './socket.js';
import { clearComposerIf, sendText } from './composer.js';
import { setView } from './nav.js';

/* ── messages ───────────────────────────── */

const GROUP_GAP_MS = 5 * 60 * 1000;   // a pause this long starts a new run of bubbles from the same sender
const NEAR_TOP_PX = 400;              // scrolled this close to the top: fetch the older page
const SVG = 'http://www.w3.org/2000/svg';
const STATUS_ICONS = {                // what our message's corner shows, and what a screen reader says
  sending: ['i-clock', 'Sending'],
  sent: ['i-check', 'Sent'],
  read: ['i-check2', 'Read'],
};
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const box = $('messages');

/** A bubble. Its text is the first child (textContent, never innerHTML); the time and the ticks follow in .meta,
 *  which floats into the last line when there is room for it. `at` is the time in ms. */
function bubbleRow({ mine, text, at }) {
  const row = document.createElement('div');
  row.className = 'row ' + (mine ? 'out' : 'in');
  row.dataset.at = at;                  // dividers and runs are worked out from it
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  const meta = document.createElement('span');
  meta.className = 'meta';
  const time = document.createElement('span');
  time.textContent = timeOf(at);
  meta.append(time);
  bubble.append(meta);
  row.append(bubble);
  return row;
}

/** Our message's state: 'sending' (a clock), 'sent' (one tick), 'read' (two) or 'failed' (no icon). */
export function setStatus(row, status) {
  row.dataset.status = status;
  const meta = row.querySelector('.meta');
  meta.querySelector('.tick')?.remove();
  if (!STATUS_ICONS[status]) return;
  const [symbol, label] = STATUS_ICONS[status];
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('class', 'tick');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', label);
  const use = document.createElementNS(SVG, 'use');
  use.setAttribute('href', `#${symbol}`);
  svg.append(use);
  meta.append(svg);
}

function messageRow(msg) {
  const mine = msg.sender_id === state.me.id;
  const row = bubbleRow({ mine, text: msg.text, at: Date.parse(msg.created_at) });
  row.dataset.id = msg.id;
  if (mine) setStatus(row, msg.is_read ? 'read' : 'sent');
  return row;
}

/** Dividers and runs, worked out again after every change, whatever order the rows came in: a divider before the
 *  first message of each day, and group-start / group-end on the first and last bubble of each run from one
 *  sender (the last one gets the tail). Dividers already in the right place are kept. */
function decorate() {
  let prev = null;          // the message above
  let divider = null;       // a divider met since `prev`, until we know whether it's still needed
  for (let el = $('message-rows').firstElementChild; el;) {
    const next = el.nextElementSibling;
    if (el.classList.contains('day')) {
      divider?.remove();    // two in a row: the first one's day has no messages left
      divider = el;
    } else {
      const day = new Date(Number(el.dataset.at)).toDateString();
      const newDay = !prev || new Date(Number(prev.dataset.at)).toDateString() !== day;
      if (newDay) {
        if (divider?.dataset.day !== day) {
          divider?.remove();
          divider = document.createElement('div');
          divider.className = 'day';
          divider.dataset.day = day;
          divider.append(Object.assign(document.createElement('span'), { className: 'service' }));
          el.before(divider);
        }
        divider.firstChild.textContent = dayLabel(Number(el.dataset.at));   // "Today" turns into "Yesterday"
      } else {
        divider?.remove();
      }
      divider = null;
      const joined = !newDay && prev.classList.contains('out') === el.classList.contains('out')
        && el.dataset.at - prev.dataset.at < GROUP_GAP_MS;
      el.classList.toggle('group-start', !joined);
      prev?.classList.toggle('group-end', !joined);
      prev = el;
    }
    el = next;
  }
  divider?.remove();        // nothing after it
  prev?.classList.add('group-end');
}

export function appendMessage(msg) {
  if (state.seenIds.has(msg.id)) return;
  state.seenIds.add(msg.id);
  const rows = $('message-rows');
  const row = messageRow(msg);
  // Rows stay in id order whatever order they arrive in: history, live, catch-up (Codex audit M-09).
  // Search from the bottom, where new messages go, past dividers, our bubble on its way and newer messages.
  let above = rows.lastElementChild;
  while (above && !(above.dataset.id && Number(above.dataset.id) < msg.id)) above = above.previousElementSibling;
  if (above) above.after(row);
  else rows.prepend(row);
  // The real message takes the place of its bubble, and of the copy put back in the composer.
  if (outbox && msg.sender_id === state.me.id && state.activeId === outbox.sent.chatId
      && msg.text === outbox.sent.text && msg.id > outbox.sent.after) {
    outbox.row.remove();
    outbox = null;
    clearComposerIf(msg.text);
  }
  decorate();
}

export function scrollToBottom() {
  box.scrollTop = box.scrollHeight;
}

/* ── our message on its way ─────────────── */

let outbox = null;   // { sent, row }: the bubble of our latest send, until the real message takes its place

/** Draw our message at once, with a clock. One at a time: it replaces a bubble that wasn't delivered. */
export function showSending(sent) {
  outbox?.row.remove();
  const row = bubbleRow({ mine: true, text: sent.text, at: Date.now() });
  row.classList.add('is-outbox');
  setStatus(row, 'sending');
  outbox = { sent, row };
  $('message-rows').append(row);
  decorate();
  scrollToBottom();
}

/** No answer, or a refusal: say so on the bubble, with a button that sends it again. */
export function showNotDelivered(sent) {
  if (outbox?.sent !== sent) return;
  const { row } = outbox;
  setStatus(row, 'failed');
  const note = document.createElement('span');
  note.className = 'not-delivered';
  note.textContent = 'Not delivered';
  row.querySelector('.meta').prepend(note);
  const retry = document.createElement('button');
  retry.type = 'button';
  retry.className = 'retry';
  retry.title = 'Send again';
  retry.setAttribute('aria-label', 'Send again');
  retry.textContent = '!';
  retry.addEventListener('click', () => { if (sendText(sent.text)) clearComposerIf(sent.text); });
  row.prepend(retry);
}

/* ── the ↓ button ───────────────────────── */

let unseen = 0;   // messages that arrived below while you were reading further up

function updateDown() {
  const fromBottom = box.scrollHeight - box.scrollTop - box.clientHeight;
  if (fromBottom < 60) unseen = 0;
  $('to-bottom').classList.toggle('is-shown', fromBottom > 200);
  const badge = $('to-bottom').querySelector('.badge');
  badge.textContent = unseen;
  badge.hidden = !unseen;
}

/** A message from the other person arrived while you weren't at the bottom. */
export function noteUnseen() {
  unseen += 1;
  updateDown();
}

$('to-bottom').addEventListener('click', () => {
  box.scrollTo({ top: box.scrollHeight, behavior: reducedMotion.matches ? 'auto' : 'smooth' });
});

box.addEventListener('scroll', () => {
  updateDown();
  if (box.scrollTop < NEAR_TOP_PX) loadOlder();
}, { passive: true });

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

/** No echo in time (Codex audit H-06). The echo may be what got lost, so look in the history. Says whether
 *  the message was there. */
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
    return true;
  }
  $('send-error').textContent = "The server didn't answer. Your message may not have been sent.";
  $('send-error').hidden = false;
  return false;
}

/** Fetch the next older page; scrolling near the top calls it. If it fails, the "Load older messages" button
 *  appears to ask again. */
async function loadOlder() {
  // One request at a time, and the cursor moves only when a page arrives (Codex audit M-10).
  if (state.loadingOlder || !state.olderQuery) return;
  const opened = state.opened;
  state.loadingOlder = true;
  $('load-older').hidden = true;
  $('load-older').disabled = true;
  const before = box.scrollHeight;
  try {
    if (!await loadHistory(state.activeId, state.olderQuery)) return;
    box.scrollTop += box.scrollHeight - before;   // what you were reading stays where it was
  } catch {
    // The cursor didn't move: the button (or scrolling up again) asks for the same page.
    if (opened === state.opened) $('load-older').hidden = false;
  } finally {
    if (opened === state.opened) {
      state.loadingOlder = false;
      $('load-older').disabled = false;
    }
  }
}

$('load-older').addEventListener('click', loadOlder);

/* ── open a chat ────────────────────────── */

export async function openChat(chatId) {
  const chat = state.chats.find((c) => c.id === chatId);
  if (!chat) return;

  state.activeId = chatId;
  state.opened += 1;
  state.olderQuery = null;
  state.loadingOlder = false;
  $('load-older').disabled = false;
  $('load-older').hidden = true;
  state.syncedUpTo = null;
  state.catchUpDue = false;
  state.seenIds.clear();

  setView('chat');
  $('pane-empty').hidden = true;
  $('pane-chat').hidden = false;
  $('message-rows').textContent = '';
  outbox = null;
  unseen = 0;
  updateDown();
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
  $('peer-avatar').src = avatarSrc(peer);
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
