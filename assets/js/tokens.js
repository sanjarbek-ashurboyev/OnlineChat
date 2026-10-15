import { API, REFRESH_TIMEOUT_MS, REVOKE_RETRY_MAX_MS, REVOKE_TIMEOUT_MS, dropped, state } from './state.js';

/* ── tokens ─────────────────────────────── */

export function saveTokens(access, refresh) {
  state.access = access;
  localStorage.setItem('access', access);
  if (refresh) {
    state.refresh = refresh;
    localStorage.setItem('refresh', refresh);
  }
}

export function clearTokens() {
  state.access = state.refresh = null;
  localStorage.removeItem('access');
  localStorage.removeItem('refresh');
}

/** The user id inside a token. Not verified: only used to compare two tokens we already hold. */
function tokenUser(token) {
  try {
    return JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).user_id;
  } catch {
    return null;
  }
}

/** true: renewed. false: the server refused the refresh token, so sign in again.
 *  Throws on a network or server error, which is no reason to sign out (Codex audit M-12).
 *  A refresh token works once (T-07), so callers share one renewal instead of each spending it. */
export function refreshAccess() {
  if (!state.renewal) {
    const renewal = renewTokens().finally(() => {
      if (state.renewal === renewal) state.renewal = null;
    });
    state.renewal = renewal;
  }
  return state.renewal;
}

async function renewTokens() {
  const session = state.session;
  // One tab of this browser renews at a time. A tab that waited then finds the token the one before it
  // saved, instead of spending one already spent and signing out (Codex review of #46).
  const work = () => (session === state.session ? spendRefreshToken() : false);
  const renewed = await (navigator.locks ? navigator.locks.request('refresh-token', work) : work());
  // Signed out meanwhile: these tokens must not sign anyone back in.
  if (session !== state.session) return dropped();
  return renewed;
}

/** Runs under the lock, so it must always settle: a promise that never does would hold the lock forever. */
async function spendRefreshToken() {
  adoptStoredToken();
  if (!state.refresh) return false;
  const session = state.session;
  const { res, data } = await postRefresh(state.refresh);
  if (res.status === 400 || res.status === 401) {
    // Without the lock, another tab can still have won: try what it saved.
    if (session === state.session && adoptStoredToken()) return spendRefreshToken();
    return false;
  }
  if (!res.ok) throw Object.assign(new Error('refresh failed'), { status: res.status });
  if (session !== state.session) return false;
  saveTokens(data.access, data.refresh);
  return true;
}

/** One request to the refresh endpoint, answer body included, ended after REFRESH_TIMEOUT_MS. A request that
 *  hangs would keep this tab holding the lock, and no other tab could renew. Timing out throws like any network
 *  error: the caller retries later and keeps its tokens. */
async function postRefresh(refresh) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REFRESH_TIMEOUT_MS);
  try {
    const res = await fetch(`${API}/auth/token/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
      signal: controller.signal,
    });
    return { res, data: res.ok ? await res.json() : null };
  } catch (err) {
    if (controller.signal.aborted) throw new Error('refresh timed out');
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** Another tab of the same account may have renewed, which retired our token. It saved the new one;
 *  take it. Never another account's: that would sign this tab in as someone else. */
function adoptStoredToken() {
  const stored = localStorage.getItem('refresh');
  if (!stored || !state.refresh || stored === state.refresh) return false;
  if (tokenUser(stored) !== tokenUser(state.refresh)) return false;
  state.refresh = stored;
  return true;
}

/* ── logout on the server ──────────────── */

/** Refresh tokens whose logout the server hasn't confirmed yet. Kept in localStorage, so a reload or the next
 *  visit finishes the job: this browser has already forgotten them, and only the server can still stop them. */
export function pendingRevokes() {
  try {
    return JSON.parse(localStorage.getItem('pendingRevokes')) || [];
  } catch {
    return [];
  }
}

/** Change the queue under a lock all tabs share. Read, change, write is three steps, and two tabs doing it at
 *  once lose one of the changes: that token's login is then never ended (Codex review of #47). */
function updatePendingRevokes(change) {
  const run = () => localStorage.setItem('pendingRevokes', JSON.stringify(change(pendingRevokes())));
  return navigator.locks ? navigator.locks.request('pending-revokes', run) : Promise.resolve(run());
}

/** End a login on the server (T-07), retrying until the server answers. A 429 or a network error must not
 *  leave the token working (Codex review of #40). Not tied to `state.session`: whoever signs in next, the
 *  old login still has to end. */
export function revokeLogin(refresh) {
  void updatePendingRevokes((pending) => (pending.includes(refresh) ? pending : [...pending, refresh]));
  attemptRevoke(refresh);
}

export function attemptRevoke(refresh, delay = 1000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REVOKE_TIMEOUT_MS);
  // The queue is the truth: another tab may have got the server's answer while this one waited.
  const retry = (wait) => setTimeout(() => {
    if (pendingRevokes().includes(refresh)) attemptRevoke(refresh, Math.min(delay * 2, REVOKE_RETRY_MAX_MS));
  }, wait);
  fetch(`${API}/auth/logout/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh }),
    keepalive: true,
    signal: controller.signal,
  }).then((res) => {
    // 400/401: the server doesn't know this token (a forgery, or not a refresh token). Nothing is left to revoke.
    // An expired token isn't one of them: the server still ends its login (Codex review of #47).
    if (res.ok || res.status === 400 || res.status === 401) {
      void updatePendingRevokes((pending) => pending.filter((token) => token !== refresh));
      return;
    }
    retry(Math.max(Number(res.headers.get('Retry-After')) * 1000 || 0, delay));
  }, () => retry(delay)).finally(() => clearTimeout(timer));
}
