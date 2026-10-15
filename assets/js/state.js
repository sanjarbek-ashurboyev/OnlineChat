export const API = '/api/v1';
export const PING_MS = 30000;          // presence keys expire after 90s
export const PONG_GRACE_MS = 10000;    // no frame for PING_MS + this: the connection is dead (Codex audit H-06)
export const ACK_TIMEOUT_MS = 10000;   // no echo by then: look in the history (Codex audit H-06)
export const START_RETRY_MS = 5000;    // the server couldn't be reached at startup (Codex audit M-12)
export const REFRESH_TIMEOUT_MS = 10000;   // a renewal holds the lock all tabs share, so it must end (Codex review of #46)
export const REVOKE_RETRY_MAX_MS = 60000;  // a logout the server didn't take is retried, waiting at most this long
export const REVOKE_TIMEOUT_MS = 10000;    // a logout the server never answers counts as failed, and is retried
export const AVATAR_FALLBACK =
  'data:image/svg+xml;utf8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">' +
    '<rect width="40" height="40" fill="#c9ced6"/>' +
    '<circle cx="20" cy="15" r="7" fill="#fff"/>' +
    '<path d="M6 40c0-8 6.5-13 14-13s14 5 14 13z" fill="#fff"/></svg>');

export const $ = (id) => document.getElementById(id);

export const state = {
  access: localStorage.getItem('access'),
  refresh: localStorage.getItem('refresh'),
  me: null,
  chats: [],
  chatPages: 1,
  activeId: null,
  opened: 0,              // bumped by every openChat; an answer for an earlier one is dropped
  sending: null,          // { chatId, text } of the message waiting for the server's answer
  peer: null,
  ws: null,
  pingTimer: null,
  retry: 0,
  olderQuery: null,       // the cursor link's query for the next older page, or null
  loadingOlder: false,
  loadingMoreChats: false,
  syncedUpTo: null,       // we hold every message of the open chat up to this id (Codex audit M-03)
  catchUpDue: false,      // a catch-up was asked for while the history loaded; run it once it's in
  seenIds: new Set(),
  session: 0,             // bumped by logout; answers for an earlier session are dropped (Codex audit H-04)
  renewal: null,          // the token refresh in flight, shared by everyone who needs it (T-07)
  reconnectTimer: null,
  ackTimer: null,
  startTimer: null,
  lastFrameAt: 0,
};

/** A promise that never settles. Returned for an answer from an earlier session, so whatever
 *  the caller does next (draw chats, save tokens, show an error) never runs. */
export const dropped = () => new Promise(() => {});
