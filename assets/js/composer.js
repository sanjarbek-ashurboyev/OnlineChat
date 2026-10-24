import { $, ACK_TIMEOUT_MS, state } from './state.js';
import { reconcileSend, showNotDelivered, showSending } from './messages.js';
import { socketSend } from './socket.js';

/* ── composer ───────────────────────────── */

export const composer = $('composer-input');

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

export function clearComposerIf(text) {
  if (composer.value.trim() === text) { composer.value = ''; composer.style.height = 'auto'; }
}

/** Stop waiting for the server's answer to our send. */
export function settleSend() {
  state.sending = null;
  clearTimeout(state.ackTimer);
}

/** Our own message coming back from the server: the send we're waiting for succeeded. */
export function isOurSend(msg) {
  const s = state.sending;
  return Boolean(s) && msg.sender_id === state.me.id && msg.chat_id === s.chatId && msg.text === s.text;
}

/** The send we were waiting for was refused, or won't be answered: say so on its bubble, and put the text back
 *  in an empty composer so it can be edited too. */
export function failSend() {
  const sent = state.sending;
  settleSend();
  if (!sent) return;
  showNotDelivered(sent);
  if (sent.chatId === state.activeId && !composer.value.trim()) {
    composer.value = sent.text;
    composer.dispatchEvent(new Event('input'));    // fit its height to the text
  }
}

/** Send `text` to the open chat. Its bubble shows at once, with a clock; the echo replaces it with the real
 *  message. Returns false if nothing was sent (one message in flight at a time, or no connection). */
export function sendText(text) {
  if (!text || state.sending) return false;

  if (!socketSend({ action: 'message', chat_id: state.activeId, text })) {
    $('send-error').textContent = 'Not connected. Reconnecting…';
    $('send-error').hidden = false;
    return false;
  }

  // `after` marks where to look in the history if the answer never comes.
  const sent = { chatId: state.activeId, text, after: Math.max(0, ...state.seenIds) };
  state.sending = sent;
  showSending(sent);
  state.ackTimer = setTimeout(async () => {
    if (state.sending !== sent) return;
    // Still pending while we look: Enter would send it twice. A late echo, logout or a dead socket settles it sooner.
    const saved = await reconcileSend(sent);
    if (state.sending === sent) (saved ? settleSend : failSend)();
  }, ACK_TIMEOUT_MS);
  $('send-error').hidden = true;
  return true;
}

$('send-form').addEventListener('submit', (e) => {
  e.preventDefault();
  // The composer empties at once: the text is on its bubble now, and comes back here if it isn't delivered.
  if (sendText(composer.value.trim())) {
    composer.value = '';
    composer.style.height = 'auto';
  }
});
