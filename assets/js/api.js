import { API, dropped, state } from './state.js';
import { refreshAccess } from './tokens.js';

/* ── api helper ─────────────────────────── */

export async function api(path, { method = 'GET', body, isForm = false, retry = true } = {}) {
  const session = state.session;
  const headers = {};
  if (state.access) headers.Authorization = `Bearer ${state.access}`;
  if (body && !isForm) headers['Content-Type'] = 'application/json';

  const res = await fetch(API + path, {
    method,
    headers,
    body: isForm ? body : (body ? JSON.stringify(body) : undefined),
  });

  // Signed out meanwhile: before anything else, or a late 401 would refresh with the next account's
  // token and send this request again as them.
  if (session !== state.session) return dropped();
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

export function errorText(err) {
  // A 429's detail is the server's own "Expected available in N seconds" (Codex audit L-03).
  const d = err.data;
  if (!d) return 'Something went wrong.';
  if (typeof d === 'string') return d;
  if (d.detail) return d.detail;
  return Object.values(d)
    .map((v) => (Array.isArray(v) ? v.join(' ') : v))
    .join('\n');
}
