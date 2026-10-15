# 040 · F-02: design system (tokens, icons, press feedback)

- **Date:** 2026-10-15 · **Phase:** Frontend redesign, Phase 1
- **Task:** F-02 in the [frontend plan](../../frontend/plan.md) · **Branch:** `f-02-design-system`
- **Files:** `assets/app.css`, `templates/index.html`, `assets/js/main.js`, `docs/frontend/plan.md`,
  `docs/frontend/screenshots/f-02/`, docs
- **Objective:** one set of named colours, sizes and timings, applied to the current layout; real icons with
  names; feedback on press; respect for dark mode, increased contrast and reduced motion.

## What was done
1. **"Before" screenshots** on `main` (`786dcea`), from a throwaway database (`onlinechat_shots`, seeded with 6
   users and 19 messages) so the dev data wasn't touched: desktop and phone, light and dark.
2. **Token sheet** at the top of `assets/app.css`: colour roles for light, dark and `prefers-contrast: more`; six
   type sizes in `rem` with size-dependent tracking; space, radius and press timing. Every rule below uses tokens.
3. **Colours: Telegram's green,** your choice. Light: white incoming and `#e3fbd0` outgoing bubbles on a soft
   green-grey background (`#dfe6cf`); dark: `#2c2c2e` and deep green `#2b5235` on `#111813`. Accent blue
   `#1f74c7` (light) and `#5eaaf0` text / `#2a72c2` fill (dark).
4. **Contrast checked** with a small script (the WCAG formula) for every text pair. All pass 4.5:1:

   | Pair | Light | Dark |
   |---|---|---|
   | Secondary text on the page | 5.30 | 5.94 |
   | Secondary text on a field | 4.70 | 4.86 |
   | Text on my bubble | 17.77 | 8.17 |
   | Time and ticks on my bubble | 4.63 | 5.54 |
   | Time on their bubble | 5.30 | 4.86 |
   | Accent text on the page | 4.79 | 6.87 |
   | White on the accent fill (buttons, badges) | 4.79 | 4.90 |
   | Text on the chat background | 4.71 | 6.30 |
   | Error text on the page | 4.98 | 6.13 |

   The first secondary grey (`#707579`) gave 4.13 on a field, so it became `#676c71`.
5. **Icons:** an SVG sprite we drew (person, log out, search, back, send) replaces the emoji. Each icon button has
   an `aria-label`; the send button is now a round icon button named "Send".
6. **Press feedback:** buttons scale to 96% on `:active` for 100 ms; rows darken at once. An empty `touchstart`
   listener in `main.js` makes iOS Safari apply `:active`. Hover only on devices with a real pointer.
7. **Checked in a browser** (Playwright, against the throwaway server): the buttons are found by the names
   "Profile", "Log out", "Search"; pressed transform `matrix(0.96, 0, 0, 0.96, 0, 0)`; with reduced motion
   `transform: none`, `opacity: 0.7`; with `contrast: more` the preview text is `rgb(75, 80, 85)` (`#4b5055`).
8. **"After" screenshots**, same views. Both sets are in `docs/frontend/screenshots/f-02/`.
9. **Results:** no test changed. Real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True`: **223 run, OK**;
   `make test`: **177 run, OK (skipped=20)**; Ruff 0.16.10 clean.

**Not done (moved to F-03, where they are first used):** the spring helper and the translucent materials
(with `prefers-reduced-transparency`). Writing them now would be code nothing calls.

**Also not done:** the layout is unchanged (F-03); the connection state is still a coloured dot only; avatars are
still the grey silhouette (F-04); ticks are still `✓` characters (F-05); `prefers-contrast` dark values were set
but not screenshotted.

## Concepts

### Design tokens and colour roles
- **Simple definition:** named values used everywhere; colours named for their job.
- **Why here:** dark mode and high contrast are now only value swaps in three `:root` blocks.
- Guide: [interface design](../concepts/interface-design.md).

### Contrast ratio (WCAG)
- **Simple definition:** how much brighter one colour is than the other, 1:1 to 21:1. Normal text needs 4.5:1.
- **Example:** `#707579` on white is 4.66 (passes) but on our field grey `#f1f1f4` 4.13 (fails).

### Feedback on press, and reduced motion
- **Simple definition:** react the moment a finger or mouse goes down. With "reduce motion" on, react without
  movement (dimming instead of shrinking).

## Walkthrough

`assets/app.css` (token sheet, shortened):
```css
:root {
  --color-bubble-out: #e3fbd0;
  --color-bubble-out-meta: #2e7d32;          /* time and ticks: 4.63 */
  --text-caption: .75rem;                    /* 12px */
  --duration-press: 100ms;
}
@media (prefers-color-scheme: dark) {
  :root { --color-bubble-out: #2b5235; --color-bubble-out-meta: #a8d8ab; }
}
.row.out .meta { color: var(--color-bubble-out-meta); }
```
The rule for `.row.out .meta` is written once; the theme decides the value.

`assets/app.css` (press feedback):
```css
:is(.primary, .icon-btn, .tab, .load-older, dialog menu button):active:not(:disabled) {
  transform: scale(.96);
}
@media (prefers-reduced-motion: reduce) {
  :is(...):active:not(:disabled) { transform: none; opacity: .7; }
}
```

`templates/index.html` (one icon button):
```html
<button id="logout" class="icon-btn" title="Log out" aria-label="Log out">
  <svg class="icon" aria-hidden="true"><use href="#i-logout"/></svg>
</button>
```
The test hook `#logout` is unchanged; the screen reader name comes from `aria-label`, the picture from the sprite.

## Problems
- The first "after" screenshots still showed the emoji. The dev server ran with `--noreload`, and Django's cached
  template loader kept the old `index.html` (CSS changed because static files are read from disk). Restarting the
  server fixed it. Root cause: **Confirmed** (after the restart the page HTML contained `i-send` twice and the icons showed).

## Decisions
- **Inline SVG sprite** over an icon font or image files: one request fewer, takes the text colour, and screen
  readers skip it (`aria-hidden`).
- **Spring helper and materials moved to F-03:** no code until something uses it.
- **One accent token for light, two for dark:** in light mode the same blue works as text and as a fill (the ratio
  is symmetric); in dark mode text needs a light blue and white-on-fill needs a dark one.

## What I should remember
- Name colours by role; put values only in the `:root` blocks.
- Check contrast with numbers: a grey that "looks fine" was 4.13:1.
- Press feedback on `:active`, hover only under `(hover: hover)`, and a non-moving version for reduced motion.
- An icon-only button needs `aria-label`.

## Review questions
1. Why is `--color-bubble-out-meta` a better token name than `--green-700`?
2. Why does dark mode need two accent tokens while light mode needs one?
3. What does the empty `touchstart` listener in `main.js` do?
4. Why are hover styles inside `@media (hover: hover)`?
5. What does a pressed button do when "reduce motion" is on, and why not nothing?
6. Why did the screenshots show old icons after the HTML changed?

<details><summary>Answer key</summary>

1. It says what it's for, so dark mode and high contrast can give it a different value (a light green in dark
   mode) without the name becoming a lie.
2. Contrast is symmetric: blue-on-white and white-on-blue have the same ratio, so one light-mode blue works for
   both. In dark mode, text sits on a dark page (needs a light blue) and white text sits on the fill (needs a dark
   blue): no single blue does both.
3. iOS Safari only applies `:active` on pages that listen for touches; without it the press feedback never shows
   on an iPhone.
4. On a touch screen the last tapped element keeps `:hover`, so a button would stay highlighted after the tap.
5. It dims to 70% instead of shrinking. Reduced motion asks for no movement, not for no feedback: the user still
   needs to see the press landed.
6. The dev server ran without auto-reload, and Django caches compiled templates, so it kept serving the old
   `index.html`. Static files are read from disk on each request, so the CSS changed.
</details>

## Next steps
- F-03: layout and navigation (frosted header and composer, the push/back transition with the edge swipe, the ☰
  drawer, connection status in words). You try it on your phone before F-04.
