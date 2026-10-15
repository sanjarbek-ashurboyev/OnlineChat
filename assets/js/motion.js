/* ── motion: springs and gestures ─────────── */

const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');

const SLOP_PX = 10;            // a finger moves this far before we decide it's a horizontal drag
const VELOCITY_WINDOW_MS = 100;
const DECELERATION = 0.998;    // the same deceleration as scrolling (Apple's sample code)

/** A spring with Apple's two settings: `response` (seconds; lower is snappier) and `dampingRatio` (1 = no
 *  overshoot). It always moves on from where the value is now, at the speed it has now: a new target mid-flight
 *  bends the motion instead of restarting it, so every animation can be interrupted. `render(value)` draws it. */
export function createSpring(render, { response = 0.35, dampingRatio = 1 } = {}) {
  const stiffness = (2 * Math.PI / response) ** 2;
  const damping = 4 * Math.PI * dampingRatio / response;
  let value = 0;
  let velocity = 0;
  let target = 0;
  let frame = 0;
  let last = 0;
  let onRest = null;

  function stop() {
    cancelAnimationFrame(frame);
    frame = 0;
  }

  function step(now) {
    const dt = Math.min((now - last) / 1000, 0.064);   // after a stalled frame, move at most 64 ms
    last = now;
    const steps = Math.max(1, Math.ceil(dt / 0.004));  // small steps keep a stiff spring stable
    for (let i = 0; i < steps; i += 1) {
      velocity += (-stiffness * (value - target) - damping * velocity) * (dt / steps);
      value += velocity * (dt / steps);
    }
    if (Math.abs(value - target) < 0.5 && Math.abs(velocity) < 10) {
      frame = 0;
      value = target;
      velocity = 0;
      render(value);
      const done = onRest;
      onRest = null;
      if (done) done();
      return;
    }
    render(value);
    frame = requestAnimationFrame(step);
  }

  return {
    get value() { return value; },
    get target() { return target; },
    /** Put the value there at once: a finger dragging it, or nothing to animate. Cancels a pending `onRest`. */
    jump(to) {
      stop();
      onRest = null;
      value = target = to;
      velocity = 0;
      render(value);
    },
    /** Move to `to`. `velocity` (px/s) hands over the speed a finger let go with; `onRest` runs on arrival,
     *  unless something sends the spring elsewhere first. With "reduce motion" on, it arrives at once. */
    to(to, { velocity: handover, onRest: done = null } = {}) {
      if (reducedMotion.matches) {
        this.jump(to);
        if (done) done();
        return;
      }
      target = to;
      onRest = done;
      if (handover !== undefined) velocity = handover;
      if (!frame) {
        last = performance.now();
        frame = requestAnimationFrame(step);
      }
    },
  };
}

/** Where a flick would come to rest: the distance a scroll launched at `velocity` (px/s) travels. */
export function project(velocity) {
  return (velocity / 1000) * DECELERATION / (1 - DECELERATION);
}

/** Past an edge, follow the finger less and less: it feels like a limit, not like the screen froze. */
export function rubberband(overshoot, size) {
  const c = 0.55;
  return (overshoot * size * c) / (size + c * Math.abs(overshoot));
}

/** A horizontal drag by finger or pen on `el`. Waits for SLOP_PX of sideways movement (a vertical one is a
 *  scroll and is left alone), then reports the distance moved since then, 1:1, and on release the speed.
 *  canStart(event, dx) decides whether this drag is ours; dx is the first sideways movement. */
export function trackHorizontalDrag(el, { canStart, onStart, onMove, onEnd }) {
  let drag = null;

  el.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'mouse' || !e.isPrimary) return;
    drag = { id: e.pointerId, x: e.clientX, y: e.clientY, active: false, samples: [] };
  });

  el.addEventListener('pointermove', (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    if (!drag.active) {
      if (Math.abs(dy) > SLOP_PX && Math.abs(dy) > Math.abs(dx)) { drag = null; return; }
      if (Math.abs(dx) < SLOP_PX) return;
      if (!canStart(e, dx)) { drag = null; return; }
      drag.active = true;
      drag.x = e.clientX;          // count from here, so nothing jumps by the slop
      el.setPointerCapture(e.pointerId);
      onStart();
    }
    drag.samples.push({ x: e.clientX, t: e.timeStamp });
    while (drag.samples.length > 2 && e.timeStamp - drag.samples[0].t > VELOCITY_WINDOW_MS) drag.samples.shift();
    onMove(e.clientX - drag.x);
  });

  const end = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    if (drag.active) {
      const first = drag.samples[0];
      const latest = drag.samples[drag.samples.length - 1];
      const dt = latest.t - first.t;
      onEnd(dt > 0 ? ((latest.x - first.x) / dt) * 1000 : 0);
    }
    drag = null;
  };
  el.addEventListener('pointerup', end);
  el.addEventListener('pointercancel', end);
}
