# Interface design: tokens, contrast, feedback

## Definition
- **Design tokens** are named values for every colour, size, space and timing in the interface, defined once
  (in our case as CSS custom properties) and used everywhere else by name.
- A **colour role** is a token named for its job, not its paint: `--color-bubble-out-meta` ("the time on my
  bubble"), not `--green-700`.
- **Contrast ratio** compares how bright two colours are, from 1:1 (same) to 21:1 (black on white). The WCAG AA
  rule: normal text needs **4.5:1** against its background; large text and icons need 3:1.

Small example:
```css
:root { --color-text-secondary: #676c71; }                     /* 5.30:1 on white */
@media (prefers-color-scheme: dark) { :root { --color-text-secondary: #98989f; } }
.chat-preview { color: var(--color-text-secondary); }           /* never a hex code here */
```

How the ratio is computed: turn each colour into its **relative luminance** L (0 = black, 1 = white; each of R, G, B
is converted from the 0–255 value to linear light, then weighted 0.2126 R + 0.7152 G + 0.0722 B, because the eye is
most sensitive to green). Then `ratio = (L_lighter + 0.05) / (L_darker + 0.05)`. Black on white:
`(1 + 0.05) / (0 + 0.05) = 21`.

## Why
- **Dark mode and accessibility settings become value swaps.** Only the `:root` blocks change; no rule below them.
- **Consistency:** a 13px caption is the same 13px everywhere, so the interface reads as one thing.
- **Contrast is measurable,** so it can be checked before anyone squints at a screen.

## How (in this project)
`assets/app.css` starts with the token sheet:
- **Colours:** surfaces, text, accent, bubbles, status, each for light, dark and `prefers-contrast: more`.
- **Type:** the system font (San Francisco on Apple devices), six sizes in `rem` (so the user's text size setting
  works), and tracking that depends on size: tighter for big text, slightly looser for small.
- **Space and shape:** `--space-1`…`--space-6`, `--radius-sm`…`--radius-full`.
- **Motion:** short press timings now; springs come in F-03.

## Feedback on press, not on release
A button that reacts only after you lift your finger feels slow. Ours scale to 96% while pressed (`:active`), for
100 ms. Two details make it work everywhere:
- iOS Safari only applies `:active` on pages that listen for touches, so `main.js` adds an empty `touchstart` listener.
- Hover styles sit inside `@media (hover: hover)`, or a tapped button on a phone stays "hovered".

## Respecting the user's settings
| Setting | CSS | What we do |
|---|---|---|
| Dark appearance | `prefers-color-scheme: dark` | Swap colour tokens |
| Increase contrast | `prefers-contrast: more` | Darker secondary text, solid separators |
| Reduce motion | `prefers-reduced-motion: reduce` | No scaling on press; a dimmed button instead |

Reduced motion doesn't mean *no* feedback: it means feedback that doesn't move.

## Icons
Our icons are an inline SVG **sprite**: `<symbol>`s drawn once at the top of `index.html`, used with
`<svg><use href="#i-send"/></svg>`. They take the text colour (`stroke: currentColor`), so they follow dark mode.
An icon-only button must have a name for screen readers: `aria-label="Send"`; the SVG itself gets
`aria-hidden="true"`.

## Alternatives
- **Icon fonts:** easy, but screen readers may read the glyphs and a failed font load shows boxes.
- **Emoji as icons** (what we had): look different on every system and can't take our colours.
- **Sass variables instead of custom properties:** fixed at build time, so they can't change with dark mode.

## Common mistakes
- Hex codes scattered through the rules: dark mode then needs a second copy of every rule.
- Grey-on-grey hints that look "clean" but fall under 4.5:1 (our first secondary grey was 4.13:1 on a field).
- Showing status only by colour (our connection dot still does; F-03 adds text).
- Removing the focus outline without a replacement; keyboard users lose their place.

## When to use
From the second screen on. Any project that will have dark mode, or more than one person changing the styles.
