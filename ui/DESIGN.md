# canopy web UI: design

The visual and interaction rules for `ui/`. Normative, like `docs/DESIGN.md`: if a component and this file disagree,
this file wins until it is changed in the same PR. How to work in `ui/` is in `AGENTS.md`; why it exists is D079.

## Direction

An operations inbox: a control room's at-a-glance state, kept calm enough to read a worker's words and answer
them. Data sits in monospace readouts on quiet surfaces, separated by hairlines, on a plain canvas. One accent color
marks what is live, selected, or the action to take. Status color is reserved for state; nothing is colored for
decoration. Dark is a cool slate, light is grey and white; neither is the lesser theme (D094). The directions weighed
are recorded in `docs/ui-explorations/2026-10-08-style/`.

## Tokens

Every color is a token in `src/styles/tokens.css`, defined in oklch for both themes under the same name. Components
use the Tailwind utility a token generates (`bg-surface`, `text-muted-foreground`, `border-border`,
`bg-status-running/15`) and nothing else.

| Token | Role |
|---|---|
| `background` | The page canvas. |
| `surface` | Panels and the header: the first layer above the canvas. |
| `surface-raised` | Hover, selected items, inputs, and anything on top of a surface. |
| `border` | Every hairline. Applied by default to `border`, so `border-b` needs no color. |
| `foreground` | Primary text. |
| `muted-foreground` | Labels, descriptions, inactive navigation, placeholders. |
| `accent`, `accent-foreground` | The one accent: active nav hairline, live indicator, links, primary buttons, focus. |
| `ring` | Focus outlines (the accent, translucent). |
| `status-running` | A run working. Pulses. |
| `status-blocked` | A run that asked a question, and anything else waiting on the operator. |
| `status-stopped` | A run the operator stopped. |
| `status-done` | A run that finished. |
| `status-failed` | A run that failed, crashed, or left no result. Also shadcn's `destructive` and refusals. |

Rules:

- **No raw colors outside `tokens.css`.** No hex, `rgb()`, `oklch()`, Tailwind palette classes (`bg-zinc-800`,
  `text-white`), or arbitrary color values. `npm run lint` fails on them (`scripts/check-source.mjs`).
- **No `dark:` in components.** Both themes are first-class and come from the same tokens. If a component looks wrong
  in one theme, the token is wrong: fix the value in `tokens.css`, for that theme. The lint fails on `dark:`.
- **Status colors** work three ways, in both themes, on `surface` and `surface-raised`: as a dot (`RunDot` in
  `src/components/status.tsx`), as text, and as a tint (`bg-status-blocked/8` behind a question). Map a state to its
  classes through a `Record<State, string>` written out in full, never by building a class name from a string:
  Tailwind only generates classes it can see.
- **Worktree states** borrow the run colors (`src/lib/worktree-state.ts`): `working` is `status-running` (it does not
  pulse; the run it names does, on the runs page), `held` is `status-stopped`, `dirty` is `status-blocked`, `broken`
  is `status-failed`. An `idle` slot is a hollow ring in `muted-foreground`: nothing holds it, so no status color
  claims it.
- **Adding a token**: define it in both `:root` and `.dark`, expose it in `@theme inline`, and add a row above. Check
  it on both themes' surfaces before using it.
- **shadcn names** (`primary`, `muted`, `card`, `popover`, `input`, `destructive`, ...) are aliased onto ours so
  generated components render unchanged. New code uses our names. shadcn's own `accent` (a hover tint) is not
  aliased: here `accent` is the brand color, so replace `bg-accent` hover tints in generated code with
  `bg-surface-raised`.

## Type

- **IBM Plex Sans** (variable) for interface text, **IBM Plex Mono** (400, 500, 600) for data: one family, so the
  two sit together on a line. Self-hosted from `@fontsource-variable/ibm-plex-sans` and `@fontsource/ibm-plex-mono`
  (Plex Mono has no variable build); the latin subsets are preloaded, so text never paints in a fallback face. A
  heavier mono weight needs its own import in `src/index.css` and a place in `PRELOAD_FONTS` in `vite.config.ts`.
- `readout`: monospace, `tabular-nums`, slashed zero. Use it for every counter, timer, cost, id, and timestamp, so a
  changing number keeps its width.
- `panel-label`: small uppercase monospace in `muted-foreground`, the label above or beside a value.
- Sizes: `text-xl` page titles, `text-sm` body, `text-xs` secondary and data-dense rows. Nothing larger, but a
  counter's value (`text-3xl`).

## Shape and space

- Hairlines: 1px `border` everywhere. No shadows except `shadow-xs` on a pressed segment.
- Radius: `rounded-md` (8px) for panels and buttons, `rounded-sm` (6px) for chips and nav items.
- The shell: a 3rem header, a 13rem side nav, content capped at `max-w-6xl` with `p-6` and `gap-6` between blocks.
  The side rail runs the full height of the page and only the nav inside it is sticky: nothing in the shell is sized
  to the viewport, so a full-page capture (or print) shows it whole.
- The header carries the stream's state (and `mock`) and the theme toggle; the counters are the attention page's,
  and the nav's Attention item shows how many items it lists, on every page.
- Pages are a `PageHeader` followed by `Panel`s (`src/components/panel.tsx`). A panel's title row is `PanelHeader`.

## Motion

- Route changes cross-fade in 160ms through the `<ViewTransition>` around the outlet. The old page stays until the
  new one is ready, because navigations run inside React transitions.
- The theme toggle reveals the new theme as a circle growing from the button, in 420ms.
- Only `running` runs pulse.
- Everything above is off under `prefers-reduced-motion: reduce`: the theme swaps instantly and pulses are hidden.

## No layout shift

- `scrollbar-gutter: stable` on the root, so a page that grows a scrollbar does not move.
- Async content gets its space before it arrives: a fixed width for readouts, a minimum height for panels.
- A skeleton (`Skeleton`) shows only while there is no data at all. A refetch or a stream update keeps what is on
  screen.

## Themes

Light, dark, and system, stored in `localStorage` under `canopy-theme` (absent means system) and synced across tabs.
The blocking script in `index.html` sets the `dark` class, `color-scheme`, and `data-theme` on `<html>` before first
paint; `src/theme/store.ts` keeps them current afterwards. Change one, change both: `theme-script.test.ts` runs the
inline script and checks it against the store's key.

## Patterns

- **Lists are rows in a panel**, divided by hairlines: a fixed-width key column (a ticket key, a state), then the
  text, then readouts (cost, age) right-aligned in fixed widths. Ages are `Age`: the CLI's largest whole unit, with
  the local time on hover.
- **Chips** (`Chip`) label a row with a fixed word: a kind, `private`, a reason. Never with journal text.
- **Counters** (`src/components/counters.tsx`) head the attention page: running, waiting on you, attention, and
  spent in the last 24 hours (`GET /api/spend`, on the stream). Each is a label, the value, and one line under it,
  with a 2px top rule in the state color it counts: `status-running`, `status-blocked`, `status-failed` while
  something is broken, the accent for spend.
- **The attention list is an inbox**: one list, most severe first, beside the selected item. Severity
  (`src/lib/attention.ts`): broken work first (a run's `crashed`, `unpushed`, `unknown_result`, `worker_failed`,
  `attempt_limit`, `chore_failed`, and the review reasons), then what waits on the operator's answer
  (`awaiting_reply`, `untrusted_review`), then every other reason, then chores' findings; within each, the item open
  longest first. A reason chip takes `status-failed` or `status-blocked` for the first two, plain otherwise. The
  selection is `?item=<id>`; with none, the most severe item about a ticket. A ticket's item shows its conversation and
  the reply form; an item about no ticket shows its detail and nothing to answer.
- **A conversation** is a column of messages, each with a 2px left rule: `border` for a worker's report or a
  tracker comment, `accent` on a faint accent tint for the operator's own words, `status-blocked` on its tint for a
  question. Bodies keep their line breaks (`whitespace-pre-wrap`) and are always text.
- **An action** is a button in an Actions panel or under its form, with one line under it (`Notice`): what the action
  did, in the CLI's words, or its refusal in `status-failed`, naming the guard. An action that kills something asks
  once more inline (Stop now, then End run N now), never through a browser dialog.
- **Signed out**, the whole page is the sign-in card, centered on the canvas: no shell, nothing from the journal.
