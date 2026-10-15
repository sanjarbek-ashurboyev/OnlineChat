import { $ } from './state.js';
import { createSpring, project, rubberband, trackHorizontalDrag } from './motion.js';
import { leaveChat } from './messages.js';

/* ── navigation: the phone's slide-over chat, and the ☰ menu ── */

const narrow = matchMedia('(max-width: 760px)');   // must match the breakpoint in app.css
const app = $('app');
const sidebar = document.querySelector('.sidebar');
const pane = document.querySelector('.pane');

/* On a phone the chat lies on top of the list and slides in from the right. --pane-x is how far it is pushed
   right: 0 when the chat is open, the screen's width when the list shows. */
const paneSpring = createSpring((x) => {
  app.style.setProperty('--pane-x', `${x}px`);
  app.style.setProperty('--pane-progress', String(1 - x / (pane.offsetWidth || 1)));
});

const paneTarget = () => (app.dataset.view === 'chat' ? 0 : pane.offsetWidth);

/** Only the panel on screen can be reached by the keyboard or a screen reader. The incoming one at once; the
 *  outgoing one once it has left, so a finger can still catch it on the way. */
function settleView({ leaving = true } = {}) {
  const chat = app.dataset.view === 'chat';
  const offscreen = narrow.matches ? (chat ? sidebar : pane) : null;
  for (const panel of [sidebar, pane]) {
    if (panel !== offscreen) panel.inert = false;
    else if (leaving) panel.inert = true;
  }
}

/** Show the list or the open chat. `velocity` hands over a finger's speed; `instant` skips the animation. */
export function setView(view, { velocity, instant = false } = {}) {
  app.dataset.view = view;
  settleView({ leaving: false });
  if (!narrow.matches || instant) {
    paneSpring.jump(paneTarget());
    settleView();
    return;
  }
  paneSpring.to(paneTarget(), { velocity, onRest: () => settleView() });
}

// The breakpoint crossed, or the phone turned: put the panels where they belong, without animating.
narrow.addEventListener('change', () => setView(app.dataset.view, { instant: true }));
window.addEventListener('resize', () => {
  if (paneSpring.value === paneSpring.target) paneSpring.jump(paneTarget());
});

// Swipe right anywhere on an open chat to go back. The chat follows the finger; on release, where the flick
// would carry it decides: past half the screen goes back, otherwise it springs open again.
let paneGrabbedAt = 0;     // where the chat was when the finger took it: it may still have been sliding in
trackHorizontalDrag(pane, {
  canStart: (e, dx) => narrow.matches && app.dataset.view === 'chat' && dx > 0,
  onStart: () => { paneGrabbedAt = paneSpring.value; },
  onMove: (dx) => {
    const x = paneGrabbedAt + dx;
    paneSpring.jump(x < 0 ? rubberband(x, pane.offsetWidth) : x);
  },
  onEnd: (velocity) => {
    if (paneSpring.value + project(velocity) > pane.offsetWidth / 2) leaveChat({ velocity });
    else paneSpring.to(0, { velocity });
  },
});

/* ── the ☰ menu: a drawer from the left ── */

const menu = $('menu');
const drawer = menu.querySelector('.drawer-panel');

// --drawer-x is how far the drawer is pushed left: 0 open, minus its width closed.
const drawerSpring = createSpring((x) => {
  menu.style.setProperty('--drawer-x', `${x}px`);
  menu.style.setProperty('--drawer-progress', String(1 + x / (drawer.offsetWidth || 1)));
});

function openMenu() {
  if (!menu.open) {
    menu.showModal();                         // focus moves in; Escape and the backdrop come with it
    drawerSpring.jump(-drawer.offsetWidth);
  }
  drawerSpring.to(0);
}

/** Close the drawer. `instant` for a sign-out: the next account must not see it. */
export function closeMenu({ velocity, instant = false } = {}) {
  if (!menu.open) return;
  if (instant) {
    drawerSpring.jump(-drawer.offsetWidth);
    menu.close();
    return;
  }
  drawerSpring.to(-drawer.offsetWidth, { velocity, onRest: () => menu.close() });   // close() returns focus to ☰
}

$('open-menu').addEventListener('click', openMenu);
menu.addEventListener('cancel', (e) => {     // Escape: slide out instead of vanishing
  e.preventDefault();
  closeMenu();
});
menu.querySelector('.drawer-scrim').addEventListener('click', () => closeMenu());
// An item closes the menu; its own handler (profile, log out) does the rest.
menu.addEventListener('click', (e) => {
  if (e.target.closest('.drawer-item')) closeMenu();
});

let drawerGrabbedAt = 0;
trackHorizontalDrag(drawer, {
  canStart: (e, dx) => dx < 0,
  onStart: () => { drawerGrabbedAt = drawerSpring.value; },
  onMove: (dx) => {
    const x = drawerGrabbedAt + dx;
    drawerSpring.jump(x > 0 ? rubberband(x, drawer.offsetWidth) : x);
  },
  onEnd: (velocity) => {
    if (drawerSpring.value + project(velocity) < -drawer.offsetWidth / 2) closeMenu({ velocity });
    else drawerSpring.to(0, { velocity });
  },
});
