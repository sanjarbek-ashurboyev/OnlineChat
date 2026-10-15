import { $, ACK_TIMEOUT_MS, state } from './state.js';
import { reconcileSend } from './messages.js';
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
  state.ackTimer = setTimeout(async () => {
    if (state.sending !== sent) return;
    // Still pending while we look: the text is in the composer, and Enter would send it twice.
    // A late echo, logout or a dead socket settles it sooner.
    await reconcileSend(sent);
    if (state.sending === sent) settleSend();
  }, ACK_TIMEOUT_MS);
  $('send-error').hidden = true;
});
