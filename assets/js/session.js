import { $, START_RETRY_MS, state } from './state.js';
import { clearTokens, revokeLogin, saveTokens } from './tokens.js';
import { api, errorText } from './api.js';
import { loadChats, renderChats } from './chats.js';
import { closeSocket, connectInbox } from './socket.js';
import { composer, settleSend } from './composer.js';
import { renderMe } from './profile.js';
import { closeMenu, setView } from './nav.js';

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

/* ── session ────────────────────────────── */

function logout() {
  // Not awaited: signing out must work offline. revokeLogin keeps trying in the background.
  if (state.refresh) revokeLogin(state.refresh);
  signOut();
}

/** Sign out of this tab only. All there is to do once the server refused our refresh token: if another
 *  tab spent it first, ending the login would end that tab's too (Codex review of #46). */
export function signOut() {
  // Nothing from this session may touch the next one (Codex audit H-04): requests and token
  // refreshes still in flight are dropped, and the socket's handlers and timers are gone.
  state.session += 1;
  state.renewal = null;
  closeMenu({ instant: true });
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
  // An answer dropped by logout never reaches its `finally`: reset the in-flight flags here.
  state.loadingOlder = state.loadingMoreChats = false;
  $('load-older').disabled = $('more-chats').disabled = false;
  state.syncedUpTo = state.olderQuery = null;
  state.seenIds.clear();
  $('lookup-form').reset();
  renderChats({ glide: false });   // state.chats is empty: every row goes
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

export async function start() {
  clearTimeout(state.startTimer);   // a manual login while a retry was waiting
  try {
    state.me = await api('/auth/profile/');
  } catch (err) {
    // Only the server refusing our tokens signs us out. A network or server error is
    // retried, keeping the tokens (Codex audit M-12).
    if (err.status === 401) {
      signOut();
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
  setView('list', { instant: true });
  renderMe();
  // The socket doesn't need the chat list, so a failed list must not keep it closed (M-12).
  connectInbox();          // one socket for every conversation
  loadChats().catch(() => {});   // the poll below tries again
}
