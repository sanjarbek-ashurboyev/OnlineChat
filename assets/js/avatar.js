import { AVATAR_FALLBACK } from './state.js';

/* ── avatars: the photo, or initials on a colour ── */

// Top and bottom of each gradient. White initials sit in the middle, where every pair gives at least 3.25:1
// (large text needs 3:1; the numbers are in session 042). A person's colour comes from their id, so it never changes.
const COLORS = [
  ['#f2665a', '#d63a3f'],   // red
  ['#f08a2c', '#c95a00'],   // orange
  ['#a07af2', '#7a4ce0'],   // violet
  ['#4fb349', '#2e8a2b'],   // green
  ['#2fb2c9', '#13809a'],   // cyan
  ['#4a9cf0', '#2468cc'],   // blue
  ['#ec6aa8', '#cc3a7a'],   // pink
];

const XML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' };

/** "Ali Valiyev" → "AV", "Ali" → "A". Array.from counts an emoji as one letter, not two halves. */
export function initials(name) {
  const words = (name || '').trim().split(/\s+/).filter(Boolean);
  if (!words.length) return '';
  const first = (word) => Array.from(word)[0].toLocaleUpperCase();
  return words.length > 1 ? first(words[0]) + first(words[words.length - 1]) : first(words[0]);
}

/** What an <img class="avatar"> shows for `user` (a participant, or state.me): their photo, else their initials
 *  drawn as a small SVG. The name goes in as text inside the SVG, so it is escaped like any other markup. */
export function avatarSrc(user) {
  if (user.avatar) return user.avatar;
  const letters = initials(user.display_name ?? user.first_name);
  if (!letters) return AVATAR_FALLBACK;
  const [top, bottom] = COLORS[user.id % COLORS.length];
  const text = letters.replace(/[&<>"']/g, (c) => XML_ESCAPES[c]);
  return 'data:image/svg+xml;utf8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 54 54">' +
    `<linearGradient id="g" x2="0" y2="1"><stop offset="0" stop-color="${top}"/><stop offset="1" stop-color="${bottom}"/></linearGradient>` +
    '<rect width="54" height="54" fill="url(#g)"/>' +
    '<text x="27" y="27" dy=".35em" text-anchor="middle" fill="#fff" font-size="21" font-weight="600" ' +
    `font-family="-apple-system, BlinkMacSystemFont, system-ui, sans-serif">${text}</text></svg>`);
}
