/* ── formatting ─────────────────────────── */

export const timeOf = (iso) =>
  new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

export function shortDate(iso) {
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay ? timeOf(iso) : d.toLocaleDateString([], { day: 'numeric', month: 'short' });
}

export function lastSeenText(user) {
  if (user.is_online) return 'online';
  if (!user.last_seen) return 'offline';
  return `last seen ${shortDate(user.last_seen)}`;
}

/** A date divider's words: "Today", "Yesterday", or "14 October" (with the year if it isn't this one). */
export function dayLabel(at) {
  const d = new Date(at);
  const now = new Date();
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (d.toDateString() === now.toDateString()) return 'Today';
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
  const year = d.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' };
  return d.toLocaleDateString([], { day: 'numeric', month: 'long', ...year });
}
