import { state } from './state.js';
import { attemptRevoke, pendingRevokes, revokeLogin } from './tokens.js';
import { api } from './api.js';
import { loadChats } from './chats.js';
import { start } from './session.js';

// The browser tests (and you, in DevTools) call these by name, as they could when app.js was one classic script.
// A module's names are private, so hand them to the page on purpose.
Object.assign(window, { state, api, loadChats, start, pendingRevokes, revokeLogin });

// Messages arrive over the socket; this poll only refreshes other people's
// online dots, which nothing pushes to us.
setInterval(() => { if (state.me) loadChats().catch(() => {}); }, 45000);

pendingRevokes().forEach((refresh) => attemptRevoke(refresh));
if (state.access) start();
