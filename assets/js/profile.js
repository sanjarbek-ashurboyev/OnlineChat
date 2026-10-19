import { $, state } from './state.js';
import { avatarSrc } from './avatar.js';
import { api, errorText } from './api.js';
import { loadChats } from './chats.js';

/* ── profile ────────────────────────────── */

$('open-profile').addEventListener('click', () => {
  $('profile-form').first_name.value = state.me.first_name || '';
  $('profile-error').hidden = true;
  $('profile-dialog').showModal();
});

$('profile-cancel').addEventListener('click', () => $('profile-dialog').close());

$('profile-save').addEventListener('click', async () => {
  const form = $('profile-form');
  const body = new FormData();
  body.append('first_name', form.first_name.value);
  if (form.avatar.files[0]) body.append('avatar', form.avatar.files[0]);

  try {
    state.me = await api('/auth/profile/', { method: 'PATCH', body, isForm: true });
    renderMe();
    await loadChats();
    $('profile-dialog').close();
  } catch (err) {
    $('profile-error').textContent = errorText(err);
    $('profile-error').hidden = false;
  }
});

export function renderMe() {
  $('me-avatar').src = avatarSrc(state.me);
  $('me-name').textContent = state.me.first_name || 'You';
  $('me-phone').textContent = state.me.phone_number;
}
