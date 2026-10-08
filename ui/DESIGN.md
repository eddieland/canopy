# canopy web UI: design

The visual and interaction rules for `ui/`. Normative, like `docs/DESIGN.md`: if a component and this file disagree,
this file wins until it is changed in the same PR. How to work in `ui/` is in `AGENTS.md`; why it exists is D076.

## Direction

A scientific instrument panel that stays legible: dense but calm. Data sits in monospace readouts on quiet surfaces,
separated by hairlines, over a faint measurement grid. One accent color marks what is live or selected. Status color
is reserved for state; nothing is colored for decoration.

## Tokens

Every color is a token in `src/styles/tokens.css`, defined in oklch for both themes under the same name. Components
use the Tailwind utility a token generates (`bg-surface`, `text-muted-foreground`, `border-border`,
`bg-status-running/15`) and nothing else.

| Token | Role |
|---|---|
| `background` | The page canvas, under the grid. |
| `surface` | Panels and the header: the first layer above the canvas. |
| `surface-raised` | Hover, selected items, inputs, and anything on top of a surface. |
| `border` | Every hairline. Applied by default to `border`, so `border-b` needs no color. |
| `foreground` | Primary text. |
| `muted-foreground` | Labels, descriptions, inactive navigation, placeholders. |
| `accent`, `accent-foreground` | The one accent: active nav hairline, live indicator, links, primary buttons, focus. |
| `ring` | Focus outlines (the accent, translucent). |
| `grid-line` | The background grid only. |
| `status-running` | A session working. Pulses. |
| `status-blocked` | A session waiting on a person. |
| `status-idle` | A session alive with nothing to do. |
| `status-done` | A session that finished. |
| `status-failed` | A session that failed. Also shadcn's `destructive`. |
| `lease-held` | A lease a session holds. |
| `lease-expiring` | A held lease near its end. Pulses. |
| `lease-released` | A lease back in the pool. |

Rules:

- **No raw colors outside `tokens.css`.** No hex, `rgb()`, `oklch()`, Tailwind palette classes (`bg-zinc-800`,
  `text-white`), or arbitrary color values. `npm run lint` fails on them (`scripts/check-source.mjs`).
- **No `dark:` in components.** Both themes are first-class and come from the same tokens. If a component looks wrong
  in one theme, the token is wrong: fix the value in `tokens.css`, for that theme. The lint fails on `dark:`.
- **Status colors** work three ways, in both themes, on `surface` and `surface-raised`: as a dot (`SessionDot`,
  `LeaseDot` in `src/components/status.tsx`), as text, and as a 15% tint (`bg-status-failed/15`). Map a state to its
  classes through a `Record<State, string>` written out in full, never by building a class name from a string:
  Tailwind only generates classes it can see.
- **Adding a token**: define it in both `:root` and `.dark`, expose it in `@theme inline`, and add a row above. Check
  it on both themes' surfaces before using it.
- **shadcn names** (`primary`, `muted`, `card`, `popover`, `input`, `destructive`, ...) are aliased onto ours so
  generated components render unchanged. New code uses our names. shadcn's own `accent` (a hover tint) is not
  aliased: here `accent` is the brand color, so replace `bg-accent` hover tints in generated code with
  `bg-surface-raised`.

## Type

- **Inter** (variable) for interface text, **JetBrains Mono** (variable) for data. Both self-hosted from
  `@fontsource-variable`; the latin subsets are preloaded, so text never paints in a fallback face.
- `readout`: monospace, `tabular-nums`, slashed zero. Use it for every counter, timer, cost, id, and timestamp, so a
  changing number keeps its width.
- `panel-label`: small uppercase monospace in `muted-foreground`, the label above or beside a value.
- Sizes: `text-xl` page titles, `text-sm` body, `text-xs` secondary and data-dense rows. Nothing larger.

## Shape and space

- Hairlines: 1px `border` everywhere. No shadows except `shadow-xs` on a pressed segment.
- Radius: `rounded-md` for panels and buttons, `rounded-sm` for chips and nav items.
- The shell: a 3rem header, a 13rem side nav, content capped at `max-w-6xl` with `p-6` and `gap-6` between blocks.
- Pages are a `PageHeader` followed by `Panel`s (`src/components/panel.tsx`). A panel's title row is `PanelHeader`.

## Motion

- Route changes cross-fade in 160ms through the `<ViewTransition>` around the outlet. The old page stays until the
  new one is ready, because navigations run inside React transitions.
- The theme toggle reveals the new theme as a circle growing from the button, in 420ms.
- Only `running` sessions and `expiring` leases pulse.
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
