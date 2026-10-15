# Frontend architecture: plain DOM vs a framework

## Definition
- **The DOM** (Document Object Model) is the browser's tree of page elements. Plain JavaScript changes the page by
  changing this tree directly: `el.textContent = 'Hi'`, `list.append(row)`.
- **A UI framework** (React, Vue, Svelte…) lets you describe what the page *should* look like for the current data
  ("state"), and it works out which DOM changes to make. In React that description is a **component**, a function
  that returns the elements for its data.

Small example, a counter:
```js
// Plain DOM: you change the page yourself, every time.
let count = 0;
button.onclick = () => { count += 1; label.textContent = count; };

// React: you describe the page for any count; React updates it.
function Counter() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount(count + 1)}>{count}</button>;
}
```

## Why it matters
With a few screens, plain DOM code is short and has no build step. As the number of screens and states grows, it is
easy to forget one place to update; a framework does that bookkeeping for you. The price is a build toolchain,
a new set of rules to learn, and new kinds of bugs.

## How React runs side work: effects
Fetching data, opening a socket or starting a timer happens in a `useEffect`. React runs it after drawing, runs its
**cleanup** before running it again, and in development mode (**StrictMode**) runs it **twice on purpose** to show
missing cleanups.

```js
useEffect(() => {
  const ws = new WebSocket(url);
  return () => ws.close();       // cleanup: without it, StrictMode leaves two sockets open
}, [url]);
```

## Two classic bugs, in any framework or none
- **A late answer for an old screen.** You open chat A, then B; A's history arrives last and is drawn into B.
  Our code guards with `state.opened` ([P-21](../problems-and-solutions.md#p-21--four-frontend-bugs-with-no-tests-to-catch-them)); in React the guard is an effect cleanup
  that ignores or aborts the old request.
- **A stale closure.** A function created earlier keeps the values it saw then. A socket handler that captured
  `activeId = A` keeps using A after you switch to B. Our code reads `state.activeId` at the moment it runs, so it
  always sees the current value.

## Our project
The frontend is plain DOM code, 934 lines that were one file (`assets/app.js`). We chose to keep it that way for
the redesign ([decision 018](../decisions/018-plain-js-not-react.md)), and split it into ES modules in `assets/js/`
first (F-01 in the [frontend plan](../../frontend/plan.md), session 039).

## ES modules (how our code is split)
- **Definition:** an ES module is a JavaScript file loaded with `<script type="module">` (or `import`). It says
  what it shares with `export` and what it needs with `import`. Everything else stays private to the file.
- **Why:** one 934-line file mixed tokens, the socket and drawing code. Modules keep each topic in its own file, and
  the `import` lines show who depends on whom. No build step is needed: browsers load them directly.

```js
// format.js
export function timeOf(iso) { /* … */ }

// messages.js
import { timeOf } from './format.js';   // the path is relative to this file
```

- **Classic script vs module:** a classic script's top-level `const` and `function` names are shared with every
  script on the page (and with DevTools). A module's are not. That is why `assets/js/main.js` puts the few names
  the browser tests call (`state`, `api`, `loadChats`, `start`, `pendingRevokes`, `revokeLogin`) on `window`.
- **Modules wait for the page:** a module script runs after the HTML is parsed (like `defer`), so `$('chat-list')`
  finds its element.
- **Circular imports are allowed** (`socket.js` imports `composer.js` and the other way round), as long as no
  module *calls* the other's functions while it is still loading. Ours only call them later, from event handlers.
- **Common mistake:** forgetting `type="module"` (the browser then refuses `import`), or a missing `export` (the
  page stops with "does not provide an export named …").

## Alternatives
- **React / Preact:** components and state; Preact is a 4 KB React-like library.
- **Vue, Svelte, Solid:** the same idea with different rules.
- **htmx / Alpine:** small additions to server-rendered HTML; a poor fit for a live WebSocket app like ours.

## Common mistakes
- Rewriting working code in a framework "to make it cleaner" and losing fixes that only lived in the old code.
- In React: opening sockets or spending single-use tokens in an effect without a cleanup, so StrictMode does it twice.
- In plain DOM code: drawing an answer without checking it still belongs to what is on screen.

## When to use which
Plain DOM for a small app, or when the hard part is logic rather than screens. A framework when many screens share
state and hand-written updates become the main source of bugs.
