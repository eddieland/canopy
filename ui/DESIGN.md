# canopy web UI: design

The visual and interaction rules for `ui/`. Normative, like `docs/design/`: if a component and this file disagree,
this file wins until it is changed in the same PR. How to work in `ui/` is in `AGENTS.md`; why it exists is D079.

## Direction

An operations inbox: a control room's at-a-glance state, kept calm enough to read a worker's words and answer
them. Data sits in monospace readouts on quiet surfaces, separated by hairlines, on a plain canvas. One accent color
marks what is live, selected, or the action to take; what is selected in a page sits on its tint. Each section of
the nav has a color of its own, for a little fun and a sense of place: its icon, the nav's highlight and label on it,
and the trail over its pages wear it, and an aurora of them runs under the header. Status color is reserved for
state, and a counter wears the color of what it counts; section colors never mark state, and nothing else is colored for
decoration, but the fun's own (Fun, below). By default both themes' neutrals carry the accent's indigo hue, so the
canvas has color of its own: dark is a deep indigo slate, light a lavender grey and white. Each can wear another
palette instead, picked apart (Themes, below). Dark is the one the operator lives in; neither is the lesser theme.
This replaced an instrument panel; it and the other directions weighed are in `docs/ui-explorations/2026-10-08-style/`.

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
| `accent`, `accent-foreground` | The one accent: active nav item, links, primary buttons, focus, live. |
| `ring` | Focus outlines (the accent, translucent). |
| `scrollbar` | Every scrollbar's thumb, on a clear track: `muted-foreground`, translucent. Set once on the root. |
| `edge` | A panel's and a float's outline: `border` by default, clear where a palette draws none. |
| `depth-panel`, `-float`, `-action` | The palette's shadows, as `shadow-panel`, `shadow-float`, and `shadow-action`. |
| `status-running` | A run working. Pulses. |
| `status-blocked` | A run that asked a question, and anything else waiting on the operator. |
| `status-stopped` | A run the operator stopped. |
| `status-done` | A run that finished. |
| `status-failed` | A run that failed, crashed, or left no result. Also shadcn's `destructive` and refusals. |
| `section-attention`, `-runs`, `-worktrees`, ... | Each nav section's color (rules below). Identity, never state. |
| `nav-label-attention`, `-runs`, ... | The nav's active label: its section's color, shaded by `nav-label-shade`. |
| `diff-add`, `diff-del` | A diff's added and removed lines: a 12% tint behind a line, and its `+` or `-`. |
| `spend-overseer`, `-idle`, `-workers`, `-plans`, `-chores`, `-reviews`, `-tasks`, `-dry-run` | Spend series fills. |
| `spend-outside` | The spend series of the sessions outside canopy: no run of canopy's. |
| `context-carried`, `context-added` | The context chart's fills: what a model call carried, and what it added. |
| `wait-1` to `wait-4` | How long something took, the quickest first: Reviews' first reviews, Health's run lengths. |
| `proposal-change`, `-decline`, `-ask` | A feedback plan's proposal chip: what it does with an item, never a state. |
| `syntax-key`, `-string`, `-number`, `-literal` | Agent output's JSON keys, strings, numbers, literals; code. |
| `code-chip`, `code-size` | Inline code's chip, a tint of its own ink, and code's size against its line (Rich text). |
| `flair-*`, `buddy-*`, `rave-dark` | Fun's own colors (Fun, below), each named in `tokens.css`. Never a status. |

Rules:

- **No raw colors outside `tokens.css`.** No hex, `rgb()`, `oklch()`, Tailwind palette classes (`bg-zinc-800`,
  `text-white`), or arbitrary color values. `npm run lint` fails on them (`scripts/check-source.mjs`).
- **No `dark:` in components.** Both themes are first-class and come from the same tokens. If a component looks wrong
  in one theme, the token is wrong: fix the value in `tokens.css`, for that theme. The lint fails on `dark:`.
- **Text reads at 4.5:1** (WCAG AA for small text), in both themes and every palette: every token used as text
  (`foreground`, `muted-foreground`, `accent`, each status, section, diff, and syntax color) on `background`, `surface`,
  and `surface-raised`, and each status on its own tint up to 20% (a chip, a destructive button, a question's bubble),
  in a selected row too, and the nav's active label on its highlight. `src/styles/tokens.test.ts` measures every pair
  from `tokens.css` and fails below it, so a token change that drops one fails `npm test`. Text is never faded with
  `opacity` to look quieter: that is what `muted-foreground` is for, and an opacity under it drops below AA. Only a
  disabled control, and a state that passes (search's last hits while the next load), dim. The ticker's `flair-*`
  colors are decoration, not held to it.
- **Status colors** work three ways, in both themes, on `surface` and `surface-raised`: as a dot (`RunDot` in
  `src/components/status.tsx`), as text, and as a tint (`bg-status-blocked/8` behind a question). Map a state to its
  classes through a `Record<State, string>` written out in full, never by building a class name from a string:
  Tailwind only generates classes it can see.
- **Worktree states** borrow the run colors (`src/lib/worktree-state.ts`): `working` is `status-running` (it does not
  pulse; the run it names does, on the runs page), `held` is `status-stopped`, `dirty` is `status-blocked`, `broken`
  is `status-failed`. An `idle` slot is a hollow ring in `muted-foreground`: nothing holds it, so no status color
  claims it.
- **Section colors**, one per section, each taken from something its page is about, so the color says what the page
  is for (`src/lib/sections.ts`; the current one from `useSection`):
  - Attention rose, an alarm light: something needs you.
  - Tickets sky, a message bubble: a ticket is a conversation with the operator.
  - Tasks chartreuse, a new shoot: a task seeds the tickets that follow it, and a shoot is yellow-green before it
    is emerald, which is `status-running`'s hue and would read as a running task on its own page.
  - Pull requests violet, the purple a merged PR turns, where every PR is headed. The reviews are under it.
  - Workspace indigo, the night shift: its runs, ticks, and worktrees carry on after the operator logs off.
  - Chores orange, a hi-vis vest: scheduled maintenance.
  - Reports gold, coins: what canopy cost, by the month and, on the spend page under it, by the day.
  - Memory pale azure, the forget-me-not. It shares done's hue, which costs nothing: its page shows no run state.
  - Settings slate, the machinery. It is in the rail's footer rather than the nav, so it needs no hue of its own and
    wears its color on its trail alone.

  A new section takes a color the same way, from what its page holds, and stays apart from its neighbours in the nav
  and from the status colors on its own page. Eight nav hues, five statuses, and the accent leave the wheel full, so a
  new one may mean moving another. They go on the nav's icons, highlight, and active label, the hairline beside the
  pages open under a section, the first step of the page header's trail, and the header's aurora and name
  (`wordmark`), and nowhere in a page's data: there a color is a state's. A page in no section (the 404) takes the
  accent.
- **Spend series** (`src/lib/spend.ts`) color a kind of agent run, or the sessions outside canopy, in the report pages'
  charts and their legends, and nowhere else: the spend page's, and the health page's failures by kind, so a kind is
  one color across Reports. They are fills, never text, so the legend's words are `muted-foreground` beside a swatch.
  Idle overseer spend is the overseer's hue, lighter, so it reads as part of it. Each reaches 3:1 on `surface` in both
  themes, WCAG's bar for a graphic, which `tokens.test.ts` measures.
- **Check fills** (`check-1` to `check-4`, `check-other`; `src/lib/ci.ts`) color the CI page's red checks by day: a
  check by its rank that window, the most often red first, never by its name, and the rest in `check-other`, the dry
  run's neutral. Hues apart from the spend series and the status reds and greens, so a check never reads as a kind of
  run or as a verdict. Fills, never text; each reaches 3:1 on `surface`, which `tokens.test.ts` measures.
- **Wait fills** (`wait-1` to `wait-4`; `src/lib/review-report.ts`) color the Reviews page's first reviews by day: a
  ramp of cool hues by how long a first review waited, the quickest lightest, never a status color, so a slow review
  never reads as a failure. The Health page's run lengths take the same ramp by their share of the timeout
  (`DURATION_BANDS` in `src/lib/health.ts`), with a run at the limit in `status-failed`, since it was stopped. Fills,
  never text; each reaches 3:1 on `surface`, which `tokens.test.ts` measures.
- **Context fills** (`context-carried`, `context-added`) draw a transcript's context chart and nothing else: a neutral
  with the canvas's indigo in it for what a model call carried, a cyan for what it added. Fills, never text, so the
  legend's words are `muted-foreground` beside a swatch; each reaches 3:1 on `surface` and on `surface-raised`, the
  picked call's, which `tokens.test.ts` measures.
- **Adding a token**: define it in both `:root` and `.dark`, expose it in `@theme inline`, and add a row above. Check it
  on both themes' surfaces before using it. A neutral, or a color drawn in one, is set again in each palette's rule.
- **Palettes.** Lavender is light's default and indigo dark's. Each other palette is a rule in `tokens.css` that sets
  the neutrals and the accent over the default's, keyed on `data-light-palette` or `data-dark-palette` on `<html>`. A
  scheme with an accent of its own wears it (Nord's, Solarized's, Monokai's, Rosé Pine Dawn's, and Gruvbox's purple);
  the others take one that suits the canvas. Light has off-white, a warm paper, sage, and the light tones of Solarized,
  Nord, Gruvbox, and Rosé Pine Dawn; dark has grey (the near-colorless neutrals the 2026-10-19 exploration drew for
  Mailroom), black, forest, plum, and the dark tones of Solarized, Gruvbox, and Monokai. A light canvas is never grey,
  which only looks dim. Every other hue is the same in all, so a component never knows which it is on, and an accent is
  read through its token, never assumed indigo; where a scheme's own bases would drop a hue below 4.5:1, the bases move,
  never the hue. A palette's accent is darkened or lightened until it reads as text there, on its own tint, and under
  `accent-foreground`, and sets `ring` with it. A scheme whose accent would pass for a status wears another of its
  colors, as Gruvbox wears its purple, not its orange, and a green canvas never takes a green accent. A scheme whose
  bases would have to move until it matched another palette is left out, as Nord's dark is. `tokens.test.ts` measures
  every palette `src/theme/palette.ts` lists, and `theme-script.test.ts` checks the inline script knows each.
  A palette sets its character too, beyond color, from a few closed choices, in the same rule, so a component still
  never knows which it is on: its corners (`--radius`: crisp, the default, or soft), its `edge` (a hairline, or none,
  where panels stand apart by their lightness alone), its depth (a soft shadow in the canvas's hue, a hard one with
  no blur, or, on black, where a shadow does nothing, the accent's glow), and its face (`--face`: interface text in
  Plex Sans, or in Plex Mono, as an editor sets it). Spacing, sizes, and layout never change with a palette, and
  neither do the status colors; only the mono face reflows text, since it runs wider, so it stays with the few palettes
  that are an editor's own look: Gruvbox's sides and Monokai. There it draws every line a step smaller, at 15/16 of
  the size asked for, in the same line boxes, so the wider face crowds less and no line changes height. The guide
  keeps the default faces under every palette (`guide-face`), since pages of prose read worse in mono. The defaults
  take the soft shadow, Gruvbox's dark the crisp corners, hard shadow, and mono face of an editor of the nineties, and
  black no edges, soft corners, and the glow.
  A palette may also give the shell's signature a form of its own, the first place it is felt: the aurora (a gradient
  hairline, a stepped bar of solid blocks, or a line that blooms), the name (the aurora's gradient, on a solid block,
  or glowing), and the nav's highlight (a tint and a bar, a solid block with the active item inked in the canvas's
  color, or a tint with the icon lit). Each form takes the room the default does, so a switch moves nothing; the
  defaults keep the first of each, Gruvbox's dark the second, and black the third.
  A palette may tune its section colors too, muted toward a scheme's own set or turned up, but each keeps its hue's
  family, which says what its page is for: a rose stays a rose, a gold a gold, though a scheme's own shade of it may
  sit a few degrees round the wheel. Each still reads at 4.5:1 there, which `tokens.test.ts` measures, and stays apart
  from the status colors and the palette's accent. Gruvbox's dark takes its own faded set, black full voltage.
  Every other palette picks from the same choices, so each reads as its own place: Gruvbox's light side as its dark
  one, Solarized's sides crisp and flat, Monokai crisp and in mono under a neon aurora, Nord's light side soft under a
  fade through Frost's blues, grey tight under one steel rule, and sage, Rosé Pine Dawn, forest, and plum soft, plum
  the softest. Off-white lays its panels on the canvas like paper.
- **shadcn names** (`primary`, `muted`, `card`, `popover`, `input`, `destructive`, ...) are aliased onto ours so
  generated components render unchanged. New code uses our names. shadcn's own `accent` (a hover tint) is not
  aliased: here `accent` is the brand color, so replace `bg-accent` hover tints in generated code with
  `bg-surface-raised`.

## Type

- **IBM Plex Sans** (variable) for interface text, **IBM Plex Mono** (400, 500, 600) for data: one family, so the
  two sit together on a line. Self-hosted from `@fontsource-variable/ibm-plex-sans` and `@fontsource/ibm-plex-mono`
  (Plex Mono has no variable build); the latin subsets are preloaded, so text never paints in a fallback face. A
  heavier mono weight needs its own import in `src/index.css` and a place in `PRELOAD_FONTS` in `vite.config.ts`.
  A palette may set interface text in Plex Mono too (Palettes, under Tokens), a step smaller, from the same files
  (`src/styles/mono-compact.css`), so no third face is ever loaded.
- `readout`: monospace, `tabular-nums`, slashed zero. Use it for every counter, timer, cost, id, and timestamp, so a
  changing number keeps its width.
- `panel-label`: small uppercase monospace in `muted-foreground`, the label above or beside a value.
- Sizes: `text-xl` page titles and the spend's totals, `text-sm` body, `text-xs` secondary and data-dense rows, and
  `text-2xs` (11px, defined in `tokens.css`) for the smallest print: a chip, the stream's state, the rail's labels and
  spend windows, and a `panel-label`. A document, long-form prose (a guide page, a plan), has one step of its own,
  `text-base`, through its utilities alone (A document, under Primitives); rich text's `#` and `##` headings are the
  one other place it appears (Rich text).
  Nothing larger, but a counter's value (`text-3xl`), and nothing smaller or between the steps: no arbitrary sizes
  (`text-[0.625rem]`). Code is the one size set against its line, not a step (`text-code`, Rich text).
- **An icon is the size of the text it sits with**: 16px (`size-4`) beside `text-sm` and in a button of the default or
  `sm` size, which sets it; 12px (`size-3`) beside `text-xs` or smaller, in an `xs` or `icon-xs` button and a segmented
  control, which set it too, and as a link out in a row. Nothing between, but a checkbox's tick, which fills its box,
  and nothing larger, but the page header's guide book (22px, `size-5.5`), which sits with the title.

## Shape and space

- Hairlines: 1px `border` everywhere inside a panel. A panel, and what floats over the page, draws its palette's
  `edge` instead, a hairline but where the palette draws none.
- Depth is used sparingly, in three places and nowhere else: a faint lift under a panel and a counter
  (`shadow-panel`), a shadow under what floats over the page, a menu, a card, a tip, a dialog, a toast, the rail's
  sheet, and the settings' save bar (`shadow-float`), and one under the primary action, the default button
  (`shadow-action`). Each is the palette's (Palettes, under Tokens), so its form changes with it, and nothing inside
  a panel casts one but a pressed segment's `shadow-xs`.
- Radius: `rounded-md` (8px) for panels, buttons, and fields, `rounded-sm` (6px) for chips and nav items, `rounded-xs`
  (4px) for a mark smaller than a line of text, a checkbox or a slot's square, at the default palettes' `--radius`. A
  palette may set its own, and the scale follows it. The scale is in `tokens.css`; no arbitrary radius
  (`rounded-[4px]`), which `npm run lint` refuses.
- The shell: a 3rem header, a 13rem side nav, content capped at `max-w-[112rem]` with `p-6` and `gap-6` between
  blocks.
  The header stays put and only what is under it scrolls (`page-scroll`), so the header spans the window's width
  and a scrollbar, or the gutter kept for one, sits beside the rail and the page, never beside the header: the
  browser paints the window's own gutter with the canvas color alone, so when the window scrolled, the header
  stopped short of its edge. The side rail runs the full height of the page, and what it holds sticks: a column as
  tall as the window under the header. Printed, the shell is not held to the window and shows the page whole; a
  screenshot test does the same by growing the window to the page (`growToPage` in `e2e/helpers.ts`).
- **Skip to content** is the first stop the keyboard reaches under the header (`SkipToContent`), from a fresh load,
  where the page's scroller holds the focus, or from the header's last control: a link, unseen until it has the focus,
  then a small box on `surface` at the page's top left. It moves the focus to the page's `main`, so the next Tab is the
  page's own first stop rather than the rail's search, a dozen nav items, its runs, and its spend. It moves the focus
  by script: `#main` under the base path would be another page's address.
- **The rail** holds two groups (`src/components/shell/rail.tsx`): at its top, the search box, the nav, and what is
  working now; at its foot, the spend, then a footer. The nav lists the sections by how often the operator opens them
  (`SECTIONS` in `src/lib/sections.ts`): what they work in first (Attention, Tickets, Tasks, Pull requests), then what
  they check now and then, down to Memory. Settings, opened least, is in the footer beside the guide instead: each nav
  item is height the sticky part has none to spare of in an 800px window. The pages under a section (Workspace's
  Runs, Ticks, and Worktrees, Pull requests' Reviews, Reports' Spend) open under its item while it is the section
  shown, so the rail says where a page is: `text-sm` rows of `h-7`, `muted-foreground`, their labels in line with the
  section's, on a 1px hairline in its color down its icon's middle. Elsewhere they stay folded, so the nav keeps its
  eight rows. The strip below `lg` keeps its icons alone; the sheet shows them as the whole rail does. Each nav item
  says on hover what its page holds, and each spend window what it covers, as a native `title`; a spend window opens the
  spend page over its week or month. Each block under the nav is a hairline and a `panel-label` over its content, but
  the spend's, where each window's name is the label. What is working is every agent run running,
  worker runs, reviews of PRs, chore runs, and task runs alike, then the worker runs waiting on the operator's answer,
  each oldest first, a ticket's latest run alone: a dot in its state's color, what it works on (the ticket's key, the
  PR, the chore, the task run's `task:N#M`, in medium weight), how long it has run (or `waiting on you` in
  `status-blocked`, the whole row on a question's tint so it shows from across the room), and under it, in sans, the
  ticket's title, the review's reference and ticket, `chore run #N`, or the task's first line, opening the run's
  page; at most four, then `+N more` to the page of
  the ones left out, or the runs page for a mix, so the sticky part fits an 800px window. The
  spend is the last 24 hours and the last 30 days from `GET /api/spend`, on the stream, in two rows: the window's name
  on the left, its cost right-aligned in a readout, so the figures line up at four digits as at one. The two rows are
  set alike, `text-xs` in `foreground`, so neither reads as a different kind of figure. The 30 days is shown nowhere
  else, but for the lifetime total Sprig's hats and the Ghost's shells are bought with (Fun, below). It sits
  right on the footer's hairline, a readout at the rail's base. The footer is two lines, the version, a link out to
  canopy's releases on GitHub, in `muted-foreground` so it does not compete with the buttons, with the width to itself
  and cut short only past a long build's hash, then the guide and Settings as two filled pills alike, `foreground` on
  `surface-raised` with no border, in the rail's body size, so they stand out from the version's print, splitting the
  hairline's width evenly, edge to edge, with a little room under them so they do not sit on the window's edge. A
  quieter pair was too hard to find. The foot sits at the foot of the sticky column, so at the window's foot however
  long the page; in a window too short for the rest, the top scrolls on its own. The room left between the two groups
  is one gap, and Sprig's slot (Fun, below): it stands on the foot.
- **Narrower than `lg`, the rail is a strip** (`useRailMode`), since a narrow window is under it and a whole
  rail there left a list too little room: 3.5rem of the nav's icons (the nav's `compact`), each named on hover and to a
  screen reader, each count one number on its icon's corner, Attention's in its most severe item's color. A button
  atop the strip opens the whole rail, footer included, the same column, as a sheet over the page (`Sheet`, a Radix
  dialog: Escape or a click outside closes it, and the focus goes back to the button). It opens in its search box, so
  `/` opens it too. A link followed or a search sent from it closes it, since the page it covered is leaving. The
  breakpoint is the viewport's, as the rail's place is the window's; what a list shows, and every other layout step
  inside the pane, is its own width's (Primitives). The UI is made for the operator's window, about 1720px wide
  (`PRODUCT.md`), where its screenshots are taken. Down to about 820px it holds up, the rail a strip, and two
  screenshots hold how it looks there: the ticket page and the tickets list. A phone's window it does not.
- **Sizes are in rem, and rem grows with the window**: the browser's size up to a 1600px window, rising to a quarter
  larger at 2560px (`font-size` on `html` in `src/index.css`). Write sizes in rem (Tailwind's scale) so a large
  screen scales them; px only for hairlines and the like. Breakpoints are not scaled.
- **Wide screens use the width** from `2xl`: the attention list widens, and a detail page puts its thread or main
  content (below) beside the rest, a ticket's conversation beside its work, runs, decisions, and memory, a chore's open
  findings and runs beside its schedule, notes, and spend. The source keeps the narrow order, which is the reading
  order; the grid only places that content in a second column (`2xl:col-start-2 2xl:row-span-N`), over rows whose
  last is `1fr`, so a long thread or list leaves no gaps between the panels beside it. Content of two panels is one
  column element spanning those rows, so the first panel's length never stretches a row beside it.
- Between the header's name and its readouts, the ticker crawls joke headlines (Fun, below).
- The header carries, after its name, the stream's state (and `mock`), then at its end the loop's pause
  (`LoopPause`) and Tick now (`TickNow`), the latest tick (`tick:12 · 3m ago`, its status when not `ok`, in
  `status-failed` when it failed or was abandoned, one link to its page, with a hover card of its summary, when it
  started and how long it took, its decisions, its overseer's cost, and what woke the loop; before the first, `no
  tick yet` in muted readout type, so a fresh workspace does not read as a quiet one), the budget's readout while a
  budget is set, the host's readout last among the readouts, and the theme toggle, in three groups with a hairline
  rule between each: the actions, the readouts, the theme. Every readout that opens a page has a hover card of it.
- The stream's readout sits beside the name (`StreamReadout`), not with the readouts at the end, so a drop moves
  nothing: its word hugs its text, and only the ticker's window gives way when it changes. Held to one width at the end,
  it left a hole before `live` whenever the loop was up. The word sits in a pill with a dot, as `mock` does in a pill
  of its own, so the name and the readout's small capitals never sit loose side by side. `live` in the accent,
  its dot breathing with the logo's, while open, `opening` and `retrying` muted
  while it connects or has just dropped, and once it has been down past the first retry's wait (`RETRY_FIRST_MS`, 5s),
  `down · 2m`, an `Age` from the drop, in `status-blocked`, when it dropped on hover. Only `canopy loop` serves the UI
  (D073), so a stream that stays down almost always means the loop stopped, and the page says so rather than look live:
  after 10s a band heads the content column, as the notice to workers does, saying the loop isn't answering, that the
  page shows what it last said and how long ago, and `canopy loop` or `canopy daemon start` as code (`LoopDownBand`).
  While it is down, Pause and Tick now wait, with the band's reason on hover; the Working rail dims to 60%, as stale
  search hits do; and an empty attention list says nothing needed the operator as of the drop rather than celebrate.
  What is on screen stays. All of it reads the stream from the shell (`useLoopDown`), and leaves the moment the stream
  opens again, with no reload.
  The readouts hug their text, inset as far as a ghost button's label, so each rule sits midway. The counters are the
  attention page's, and the nav's Attention item shows how many items it lists, on every page, split by severity:
  broken in `status-failed`, waiting on the operator's answer in `status-blocked`, the rest muted, each only when there
  is one. Never in the section's rose, too near the failure color to tell apart at that size. Since color alone tells
  the numbers apart, they are said in words on hover and to a screen reader (`1 broken, 1 waiting on you, 3 other`;
  `breakdown` in `src/lib/attention.ts`). That split is the nav's alone: the Attention counter does not say it again
  under its value, on the one page that shows both (Counters, below). The Memory item shows how many proposals wait on
  the operator, in `status-blocked` as what waits on their answer is, said in words (`2 proposals waiting on you`), and
  nothing while none waits or proposals are off. It comes with the loop's state on the stream, so it moves as a run
  proposes and as the operator promotes or rejects. The Reviews item shows how many reviews with a result to read the
  operator has not seen (findings, or any verdict of one they requested: `news` on each), in the color of the worst
  finding among them as a verdict wears it, the rest muted, said in words (`2 new reviews to read`). What they have
  seen is the journal's (DESIGN §22), on each review in the list: a review's page marks it as it shows the result, and
  the reviews list's header marks every new one. A new review's row, wherever a list shows it, has a dot in `accent`
  after its verdict.
- **The pause** is the header's standing action, since it is about the loop, not a page's subject: a ghost Pause
  button while the loop runs; paused, `paused · 3m` in `status-blocked` (the loop waits on the operator; when and
  from where on hover) and a Resume button. The button keeps one width in both states. It has no `Notice`: what it
  did is the state it shows, which the stream also sends when the loop's terminal or the CLI pauses. A failure colors
  the button `status-failed`, with the reason on hover and in an `sr-only` alert.
- **Tick now** stands after the pause, a ghost button beside the latest tick's readout, which shows the tick it starts:
  `t` at the loop's terminal, so the loop's wait ends at once, paused or not. It is disabled while the latest tick
  runs, and from the click until the tick it asked for starts, which the readout and the logo show as starting
  meanwhile: the loop takes the ask at its wait's next step, after a poll of the sources if one is under way. Like the
  pause it has no `Notice`, since the tick it asked for shows in the readouts, and a failure looks the same.
- **The budget's readout** (`BudgetReadout`) is the local month's spend against the monthly budget, while one is set:
  a wallet's icon and the percent spent, `39%`, muted while on budget, in `status-blocked` once the month's pace heads
  over, and in `status-failed` once it is over, the spend page's word for it and its line (`Headed over: $15.76 of $40
  (39%), on pace for $63.04.`) as its accessible name, and a hover card of the month: what it spent, its pace, how
  much of it has gone by, and what the spend is made of. Short of `2xl` the icon stands alone in its color:
  the ticker needs the room, or a tick's readout widening as the tick starts steps it out. It opens the spend page.
  It comes with the spend on the stream, which sends it again when a cost or the budget changes.
- **The host's readout** (`HostReadout`) is the machine the loop runs on, which serves the page: a server's icon and
  `host ok` in muted readout type, or its worst pressure in two words (`disk low`, `memory low`, `host busy`) in
  `status-blocked` while worth a look and `status-failed` past what canopy works with, a disk under the tick's
  free-space floor among it (`src/lib/host.ts` holds the thresholds). Under `lg` the header has no room for the words:
  the icon stands alone in the pressure's color, as the strip's icons carry their counts, its words its accessible
  name and the card's. It is a link to the system resources page, in no section, with a hover card over it: the
  machine's name and system, what is under pressure, the load, the memory, each disk canopy writes to, and the
  loop's process. It shows nothing until its first read lands. Its read is not on the stream, since none of it is in
  the journal: it is read every 10 seconds while the tab is visible, as the worktrees are.
- **The notice to workers** (`NoticeBanner`, `canopy notice`) heads the content column, above every page, only while
  one is in force: a band on a `status-blocked` tint with its border, since every run waits on what the operator said,
  the notice's words through `LinkedText`, until when runs hear it (when and from where on hover), and ghost Edit,
  Renew, and Clear. Edit opens the Settings form (`NoticeForm`) in place of the words, starting from them, its toggle
  group led by `Until` the time it lapses, picked, and `Save notice` with a ghost `Cancel`, disabled until the words or
  the time change. Renew sets the same words again for as long as they were set for, its duration on hover.
  It is not in the header, which has no room for a sentence, and it leaves with the stream's word when it lapses.
  Settings sets one, in its own panel, with how long it lasts as a toggle group; any other duration is the CLI's.
- **A chore over its finding limit** (`ChoreLimitBanner`, docs/design §19) heads its page, under the title, only
  while its latest ok run counted findings past its `max_findings`: the same band as the notice to workers, on the
  `status-blocked` tint, since only the operator can settle it, saying by how much and the two ways out (raise the
  limit, or narrow the chore with a note). It has no button: both ways out are the operator's words, in config or a
  note, and it leaves once a run fits.
- **Agent memory** (docs/design §28) shows only while a tier is on, and always says each tier's mode in words, never by
  color alone, so recorded memory is never taken for memory in use. The header's readout, after the latest tick, is
  `memory: recording` or `memory: in use` in muted readout type, each tier's mode to a screen reader and, with what
  reads it and the proposals waiting, in a hover card,
  opening the memory page, which is in no section and so reached from there. A tier's **band** heads its panel there and
  on a ticket's page: a chip naming the tier and its mode (the running tone at `use`, plain while recording) and the
  server's sentence on what reads it. A ticket's page reads its notes far less than it decides, so its Memory panel,
  last in the left column under its decisions, is folded on each visit: its count, the band, and `Show 3 notes`, which
  opens the rows and, folded again at their foot, the digest (`Show what its next run is served`, `MemoryDigestFold`);
  with no notes it is its header alone, counting `0`, as an empty list's is. What a worker wrote is `MemoryText`:
  plain text, never `LinkedText`, since a link in a note would be a worker's link read as canopy's, with each
  character that hides text named (`<U+200B>`) on a `status-failed` tint, so it is seen. A digest is the prompt's own
  text in monospace, labelled `would be served at use` while recording. A run's page has it folded (`FoldPanel`): its
  header counts what the run wrote and read, `wrote 2 · read none`, each tier's mode for the run on hover and to a
  screen reader, and `Show memory` opens the rows; it reads `none, recording only` for a run that read nothing because
  its tier was recording. The memory page leads with what waits on the operator: a Proposals panel, counted in
  `status-blocked` while one waits as the nav counts them, and saying that none reaches a run until promoted;
  then Lessons under the tier's band, the pinned ones first as runs are served them, under a `Pinned` heading with a
  filled pin in `foreground` and their count, then the rest under `Up for review` (headings only while one is pinned),
  and a pinned row's line of where it came from leads with the same pin and `pinned`, the digest folded at its foot
  (`Show what every run is served`); then Ticket notes, a row a ticket opening to its notes, which it reads only then,
  counted `2 tickets · 3 notes`. From 120rem,
  the tickets sit beside the queue in 34rem, where their opened notes' columns fit and the queue still keeps a
  proposal's verbs on one line; narrower, they stack under it. Under every panel, and under the panel saying memory
  is off, a muted `xs` line says purge deletes many memories' text from the shell alone, then `canopy memory purge` in
  monospace with a `Copyable` that copies the verb alone, never an option, so a paste purges nothing until the operator
  names what, then its options (`MemoryPurge`), since purge is the one memory verb the page leaves to the CLI. Over all
  three, a filter field and a repository picker (`RepoFilter`) narrow the page (`?q=`, `?repo=`,
  `src/lib/memory-filter.ts`), as the tickets filters do: a word in a memory's key, text, ticket, or
  repository, or a ticket's key or title, and, since the page holds only each ticket's count of notes, what notes say
  through `canopy memory search`'s operator search (`GET /api/memory/search`, every word, as the rows above hold them,
  but each a whole word, its English endings aside, where a row's may be part of one), listed under the tickets as
  Notes that say it, each with its verbs, counted in the header as `N notes found`, and `50+` with a muted `the best 50`
  beside the label at the server's cap; while a repository is chosen, Ticket notes says it is not narrowed by one,
  since a note is read by its own ticket's runs in any repository; a lesson for every repository is kept whichever are
  chosen.
  While lessons are in use, the Lessons header has `all`, `due`, and `wrong` chips with their dots (`?show=`). A
  filtered count says `2 of 7`, and an empty result says which filter left nothing. The proposals flip with an
  `OrderToggle`, oldest first by default, which is the nearest to lapsing. A single `history` chip at the end of the
  filter bar, which acts on every panel (`?history=true`, `GET /api/memory?history=true`), lists each panel's latest
  memories no longer pending or in force under the rest, Decided and Retired, at most 50 each, with their standing and
  reason and no verbs; turning it on or off keeps the panels and the rows opened on them, the sections holding a row's
  skeleton until read. Each list scrolls in its panel but the proposals, which hold 20 at most and so grow with their
  rows. A row in force that its digest's cap leaves out says so in its second line, in the same words for served and
  recording that the digest's label keeps apart. The verbs on memory (`src/components/memory-actions.tsx`) sit in a line
  under a row, `xs` as a row's buttons are, and only while lessons are on, but Forget under a ticket's note, which shows
  while ticket notes are on, since forgetting a note needs no lesson; a tier that is off shows no panel on the memory
  page, so with lessons off it holds Ticket notes alone: under a proposal an outline `Promote as written`, which saves
  at once, since most proposals need no edit, and a muted ghost `Edit and promote`, which opens the form (a private
  ticket's run's proposal, whose words may hold what the operator kept off the tracker, and one whose key a lesson in
  force has, which it would replace, have `Promote` in place of both, which opens the form and what it says before the
  save, the latter with a muted `replaces memory:N` beside it, and on an attention item, which has no form, a muted line
  saying to promote it from the memory page; until the lessons in force are read, `Promote as written` is disabled, and
  if that read fails, a muted line says so and to promote it from the memory page), then, apart from both
  at the line's end, a ghost `Reject`, which cannot be undone, `Promote` under a ticket's note that keeps its text, on
  the memory page as on its ticket's, and `Renew` under a lesson, outlined once it
  is `due` or `wrong` and a muted ghost before, since only then does it ask for a decision, then a muted ghost `Edit`
  (on the memory page alone, not an attention item); a lesson that asks nothing
  shows its line only while its row is hovered or holds the focus, as a row's copy button does, over the row's end on
  `bg-surface`, so at rest it takes no room and nothing moves when it shows, and always, in the row's flow, on a touch
  screen, and in the flow too while the row's versions are open, which are then its end; each ends its line with a
  ghost `Forget`, muted at rest, the rarest verb and one that cannot
  be undone, and in `status-failed` while its row is hovered or it has the focus, but on an attention item. A memory's
  row leads with its standing, a dot and its word in a run state's color (`memoryStand`): `wrong` (failed) and `due`
  (blocked) for a lesson that calls for the operator, `pending` (blocked), `active` (done), `superseded` or `invalid`
  (stopped), and `recorded` (stopped) for one in force under a tier that only records, which no run reads, so a row
  never reads as in force under a `recording` band; then its ref, its ticket in a list across tickets, its repository's
  chip, each in a fixed column, the key in the free column, and its use only once a run relied on it. Under the text,
  one line says where it came from, the commit on the run's hover, a proposal's run's end, ticket, and `private` chip
  (`ProposalFacts`) among it. In a list of proposals, where every row is pending, the standing says the time left in its
  place (`3d left`, muted, in `status-blocked` in the last two days, `lapsing` once past). On the memory page the
  Lessons and a ticket's opened notes take the Proposals' columns (`memory-across`), the ticket's empty, so key and text
  line up down the page, and the tickets with notes flip with an `OrderToggle`, newest first by default; and a ticket's
  opened notes sit on `surface-raised` at 40%, so they read as its own. A ticket's row on the memory page carries its
  title (`TicketTitle`). A row's ref copies (`CopyButton`, shown on the row's hover), since Forget asks for it typed. A
  lesson names what it was promoted from, as the CLI does, and when a run reported it wrong. **Edit and promote** (or
  `Promote` under a note) opens its form in place of that line, on the surface with a hairline: the lesson's words in a
  field, starting as the source's own, with their count against the bound in the readout at its corner (in
  `status-failed` past it, when the button is disabled); the repository whose runs read it as a repository picker of
  one (`RepoSelect`), `every repository` first for a source that names none; a muted line naming the lesson in force
  under its key that it would replace, as plain `MemoryText`, reserved while the lessons are read; the CLI's warning
  in `status-blocked` while the text is still a private ticket's run's own words; and `Promote memory:5` with a ghost
  `Cancel`. **Forget** asks for the memory's ref typed out, in the same form as a ticket's Forget asks for its key
  (`ForgetForm`). A row can leave once its verb is done, so what it did is said once, in the CLI's words, under the
  panel's header or band, and only a refusal stays under the row, but one saying the memory changed under it
  (`not_pending`, `forgotten`, `unknown`, decided from the attention list or the CLI), which reads memory again, so its
  row may leave, and is said under the list too; proposals all decided from the page say so in the accent. On the
  attention list, a `memory_proposal` item lists its proposals with `Promote as written`, which saves at once, but for
  those two, and `Reject`; a `lesson_review`, its lessons due with `Renew` alone. **Edit** opens its form in place of
  the lesson's line, the promote form's fields (`LessonFields`), its repositories `every repository` first, then the
  lesson's own, then the rest; a muted line saying the version it replaces stays in the lesson's versions; and `Edit
  memory:8` with a ghost `Cancel`, disabled until the words or the repository change. A memory with more than one
  version says `version 2` on its line of where it came from, and a lesson edited `edited from memory:8`; under that,
  `Show versions`, a `Disclosure`, opens its versions, read only then: a list with a hairline at its left edge, newest
  first, each a line of `v2`, its ref, its status word, its repository's chip, how it was made, its age, and `this row`
  on the row's own, then its words as `MemoryText`, muted once out of force, with a ghost `Forget` under each out of
  force that keeps its text wherever the row has verbs.
- **Reload** stands before the pause only while the server serves a newer build of the UI than the page loaded
  (`NewerBuild`): a ghost button on the accent's tint at 14%, its label in the accent, the action to take without a
  fill that outshouts the ghost buttons beside it, saying on hover why and that unsent text is lost. It never
  reloads on its own, since the operator may be typing. The page knows its build from the `canopy-build` meta tag the
  server writes into index.html, and the server's from `GET /api/meta`, read again whenever the stream comes back:
  a loop restarted on an upgrade drops it.
- Pages are a `PageHeader` followed by `Panel`s (`src/components/panel.tsx`). A panel's title row is `PanelHeader`,
  on `surface-raised` at half strength with its label in `foreground` at weight 500, so it stands apart from the rows
  under it; half, so a ghost button's hover in it still shows. In a panel too narrow for one line, what is on its
  right wraps under the label. A `sticky` header, an editor's toolbar, stays at the top of the page while its panel
  scrolls under it, the same half step laid over `surface` so that the rows under it do not show through. The page
  header's trail starts in its section's color; a panel's label never takes
  one. A page's main list is named for its page's noun (Reviews on
  Reviews, Attention on Attention), and a chore's notes are Notes. A panel is named for its noun, never for how it is
  cut, and counts what it lists: a list of runs is Runs on every page, the runs page's, a ticket's, a chore's, and a
  PR's, and how the runs page filters it (by kind and state) is a label in its header, not its name.
  Its title wraps (`min-w-0 break-words`) inside an unbroken word, since it can be a ticket's title or a search's
  query: a pasted URL widened the page. Its description is `text-balance` up to `max-w-3xl`: most fit on one line on
  a wide screen, a longer one splits into even lines rather than leaving a word or two on its last, and a command in it
  (`code`) never breaks across lines. Prose inside a panel keeps the same measure, `max-w-3xl`, however wide the
  panel: Settings' explanations, the sentence under Spend's totals, as the guide's article and a plan do.
- **One heading ladder**: a page has one `h1`, its `PageHeader`'s title; every panel's label is an `h2`; what heads a
  part of a panel (a run's memory's `Wrote` and `Read`) is an `h3` in `panel-label` type, and a part of that an `h4`
  (each kind of memory under them, a chip naming it); and a plan's own headings
  start under its panel's, its `#` an `h3` (`PlanHeading` in `src/lib/plan-schema.ts`, styled by its `data-level`).
  No level is skipped, so a screen reader's list of headings is the page's outline; `e2e/headings.spec.ts` holds every
  route to it. A list of links named by its region (the guide's sidebar groups) is not a heading.
- **A detail page leads with what it is about.** Its title is its subject's, after its reference in a muted
  monospace (`PageHeader`'s `subject`), as a ticket's page has always led: `run:39 Debounce search input`,
  `acme/web#88 Debounce search input`, a review's `review:4 acme/web#88` then its PR's title, its ticket's while the
  PR has none. With no subject (a tick, a chore run, a PR canopy only reviews, a ticket untitled yet), the reference
  alone is the title. Its description is that subject's state, a line of facts (`src/lib/descriptions.ts`):
  `done · implement · ABC-099`,
  `review:4 3 findings, 1 major · at its review limit`, `ok · 5 decisions · woken by timer`, a chore's `choreLine`,
  so no two pages of a kind say the same thing there. What every page of its kind shows, the same each time, is its
  `help`, on the title's hover, as the nav's items say what their pages hold. A ticket is named one way in every
  identity panel that names one (`TicketField`: its key, then its title). A run's page names its ticket in its
  description instead, the key a `TicketLink` after its state and kind (a resume's with its reasons,
  `resume (ci, review)`), since its title is the page's already.
  A tick's page steps to its neighbours from the right of its title's row (`PageHeader`'s `controls`, `TickSteps`):
  two ghost `xs` links, `‹ tick:40` and `tick:42 ›`, through every tick by id, dry runs included, found by query so a
  gap is stepped over. At an end the button stays, disabled, saying on hover there is none, so the pair never shifts;
  there is no button to the latest, which the header's readout links to.
- **One home per fact.** What a page says, it says once. Its subject's own name is its title, so the lists under it
  leave it out: on a ticket's page its runs leave out the ticket (`ticket={false}`); on a PR's page its runs and
  decisions leave out the PR (`ownPr`), and so does its review limit (`reviews`). A PR's phase is its title's chip, not
  a field too; a ticket's phase is its Work panel's field, not its description too; whether a ticket is private is
  its title's chip, not a notice under its actions. A run's, a tick's, a chore run's, and
  a task run's pages put each fact in the same home: the state, a run's kind, and its ticket in the description, so
  the identity panel's header is its name alone and its fields leave out the ticket; a chore run's chore and a task
  run's task in the trail, never a field; the session in the transcript's header, never a field; and the paths in the
  identity panel, but a tick's output, whose path its Output panel names.
- **A detail page has one skeleton**: what it is, then its thread or main content, then the lists that support it.
  First the identity panel, its subject's fields (a ticket's Work, a run's Run, a PR's Pull request, a chore's
  Schedule); its actions sit in that panel's foot, under a hairline, never in a panel of their own above the content,
  but for a ticket's, which follow its reply (The answer, below).
  What runs and ends, a run, a tick, a chore run, a task run, keeps one order there, the page's answer first:
  `summary`; then what came of it (a task run's `question`, a failed run's `ended on`, a running run's `last call`, a
  run's PRs, a chore run's and a task run's `harness` note, a task run's tickets; a chore run's findings are counted
  in its description and listed under the panel); `when` (`WhenField`), started, ended, and how long it took in one
  field, `Oct 8 06:30 → 06:59 · 29m`, and its `span` age (`for 3m` while it runs); `spent`; then a tick's canopy
  version; then the paths, a run's branch, worktrees, and log, a chore run's log, a task run's branch, pushed commit,
  and log. A run given a checklist has its answers in a panel of their own under that one (`ChecklistPanel`), before
  its transcript: what came of it, a row an item, too many for a field. An answer is a chip, `held` in
  `status-blocked`, since a reviewer reads its reason under it, and the rest plain.
  Then the thread the operator came to answer, with its form: a ticket's conversation and the reply, then the
  ticket's actions. A page with no
  thread has its main content there instead: a run's and a task run's transcript, a chore's open findings and runs, a
  chore run's findings and transcript, a tick's decisions, a review's findings and diff, a PR's reviews. A chore's
  notes are a thread nothing waits on, written now and then, so they follow its main content, with its spend. Then
  the supporting lists: runs, decisions, spend, and a ticket's memory last, the least read. So in a narrow window a
  ticket's reply is reached before its runs and decisions, and the attention detail, the other place a ticket is
  answered, reads in the same order: the item, then what its reason asks for first (below, "The attention detail"),
  then its conversation, the reply, and the ticket's actions. An action over a whole list
  sits in that list's panel header, as a transcript's All open does: the worktrees' Read again heads their one Pools
  panel, a section per pool in it. A ticket's plan is on a page of its own, `/tickets/$key/plan`, under the ticket in
  the trail; the ticket's page has its card (`PlanCard`), and a `plan_review` item shows it too: the plan's reference
  and status chip in its header (`PlanChip`: `waiting on you` in `status-blocked` while the plan waits on the
  operator, as everything that waits on them reads; `changes asked` in `status-running` while changes the operator
  asked for wait on the next tick's planner; else its status; with no plan, `needed` or `not needed`), the run that
  wrote it and its open comments as fields; and in its foot `Approve`, the primary, while the plan can be approved, then
  `Open plan`, outlined, and a line on what comes next or what approving leaves out. Changes asked that no planner has
  started on are a band (`ChangesAsked`), the chore limit's shape on the `status-running` tint, since the loop acts on
  them next: in the card above its foot, and under the plan page's header, never a muted line a request can hide in.
  A ticket whose plan waits on the operator (proposed, no planner running) leads with the card, above its Work panel,
  since the plan is what they came to answer; otherwise the card follows the lists. Where it sits is settled as the
  page opens, so a plan approved meanwhile leaves its card where it was read. A review's run is on a page of its own
  too, `/pull-requests/reviews/$id/run`, under the review in the trail, with a run's skeleton: its Run panel, its
  transcript, its prompt, and its output. The review's page is its results, so it says only when the run ended and links
  there from a `run` field.
- **Every page header opens with its trail**, a breadcrumb (`nav` named Breadcrumb) in `panel-label` type: the
  section's name in its color, then the pages between it and this one. On the section's own list the name is plain
  text; on any page under it every step is a link and ends in a small chevron, pointing at the title. A page in no
  section (search, the 404) names itself there in the accent. A parent is a journal name, so it keeps its case
  (`chore:deps` on a chore run) and stays muted until hovered. The title is the trail's last step, so the trail never
  repeats it. The trail follows the URL, not the journal: a run's page is under Workspace's Runs, not its ticket,
  which its panel links. What qualifies a page, `private` or `dry run`, is a `Chip` beside the title, never a word in
  the trail. Where there is no title to qualify, a ticket's attention item, its `private` or `public` chip heads its
  conversation.
- **A book at the header's top right** opens the guide's page about the page shown, at the heading about it when it has
  one (a run's page at `runs#a-runs-page`), named `The guide: Runs and worktrees` on hover and to a screen reader: a
  closed book with lines of text (`BookText`) at 22px in a ghost `icon` button, sized to the title beside it rather
  than the body text, so it is there when wanted and quiet when not. Which page each route opens is `PAGE_GUIDES`
  in `src/lib/guide.ts`, keyed by route id, so a new route fails the type check until it names one. The guide's own
  pages, and the 404, have none.
- **The tab** names the page too: `PageHeader` renders a `<title>` (`pageTitle` in `src/lib/page-title.ts`), which
  React puts ahead of `index.html`'s. A tab is narrow and cut from the right, so it leads with how many attention
  items block work, when any do, then the page's name, then `canopy`: `(3) ABC-102 Export reports as CSV · canopy`.
  The count leaves out what only waits on someone else, a PR's `needs_reviewer` or `ready_to_merge`, and chore
  findings, which report rather than block (`blocking` in `src/lib/attention.ts`): a count that never falls to zero
  while PRs sit in review would stop meaning anything. The name is the header's title when that is plain text, else
  its `tab`; the sign-in page's is `Sign in`.
- **The tab's icon** is the header's mark in the accent, since a pinned tab shows no title. While anything blocks
  work, the items the title counts, a dot on its top right corner, cut out of the ring, wears the most severe one's
  color: `status-failed` for something broken, `status-blocked` for something waiting on the operator's answer, muted
  for the rest (`faviconDot` in `src/lib/favicon.ts`). Signed in, the page draws it from the theme's tokens
  (`Favicon`); `public/favicon.svg`, the plain mark in each theme's accent, is the icon before sign-in and the API
  docs'. It is static: a tab that moves pulls the eye from whatever the operator is reading.
- **The nav wears the sections' colors**: every item's icon in its own, and the active item's highlight a 24% tint
  with a 3px bar down its full height, its label at medium weight in the section's color. On a page under a section
  (Ticks, or a tick's page), the highlight is on that page's item, in its section's color, and the section's label
  stays in `foreground`, untinted. Light's section colors sit near 4.5:1 on the bare canvas, so on their tint the
  label is shaded toward black (`nav-label-shade`); dark's is not.
  In a page, **selected is the accent's tint**: the selected inbox row (`bg-accent/14`) and the runs page's chosen
  filter (`bg-accent/16`). Hover stays `surface-raised`, so selected and hovered differ.
- **The aurora**: a 2px hairline along the header's foot, over its border, fading through the nav's colors in the
  nav's order, Attention's rose first and Memory's last. It is static.

## Fun

canopy should be a little fun to use (PRODUCT.md): the header's ticker, Sprig at the foot of the rail, the empty inbox
and the leaf a cleared item drops (an approved plan drops one too, and so does a review draft once published, not
staged), the lightswitch rave, and 2048, typed anywhere but a text field. Fun is ancillary, so this design holds only
the rules it all keeps; what each one does is written in its code. None of it is journal text.

- **Fun never covers data, and never squeezes it.** Each has a place of its own in the layout. Where the window
  leaves it too little room to be read, it steps out entirely, rather than shrinking, clipping, or sitting on
  something; its room stays, so nothing beside it moves. The fit is measured as the layout changes (`useFits` in
  `src/hooks/use-fits.ts`), before the first paint, so what does not fit never flashes in. Three exceptions, all the
  operator's call: Sprig may stand over the foot of the rail's working runs by 40px rather than step out, offering tips
  there only when clicked; the rave covers the whole page, taking no pointer, hidden from a screen reader, not printed;
  and 2048 opens over the page as a dialog, only when typed, and Escape puts it away.
- **Fun is never colored as state.** Its colors are its own tokens (`flair-*`, `buddy-*`, `rave-dark`) or the accent,
  never a status color, so nothing in it reads as a run's state.
- **Fun never fakes state.** A cleared item's row leaves after the item is already gone from the list and counters.
- **A tip is true; a joke never looks like one.** The ticker's tips open with "Tip:" and name a real key, command, or
  setting in its own words; one that stops being true is fixed or dropped. Nothing else opens with "Tip:".
- **Fun honours reduced motion** (Motion, below): it holds still, and says the same. Nothing flashes more than twice a
  second, well clear of the three that WCAG 2.3.1 counts as harmful.
- **Settings has one Fun panel**, second to last, below the settings that change how canopy works and above Session:
  an on/off for each, as checkboxes, then each one's details. Everything in it is kept in this browser (Themes, below).
  The rave is the one without a checkbox: its switch hides in the panel's header. 2048 is not in the panel at all:
  nothing of it shows until it is typed.

## Motion

Motion says something arrived or changed, and gives the page some life without asking for attention. It is short
(at most 700ms), eased out (`cubic-bezier(0.2, 0, 0, 1)`), and never loops on anything but the logo, a running run,
a skeleton, and fun (Fun, above). The keyframes and utilities are in `src/index.css`.

- Route changes cross-fade in 160ms through the `<ViewTransition>` around the outlet. The old page stays until the
  new one is ready, because navigations run inside React transitions. A transition that redraws part of a page, as a
  transcript's search does at each key, is typed `in-page` (`inPage`), and the outlet leaves it be: cross-faded, each
  key waited on a snapshot of the whole page.
- A page's blocks rise in one after another (`stagger` on the page column), and so do the attention list's rows, the
  Working rows, and a conversation's bubbles. Any other list's rows arrive with their panel, as one block. A row or
  bubble the stream adds later rises in on its own. A bubble pops (`[--enter:pop]`) from the corner nearest its side.
  A reply's `seen` pops in once (`animate-receipt`) when a tick reads it while the page shows it, never on a page that
  opens on it already read.
- Counter values are odometers (`RollingNumber`): each digit rolls to its new value, the units first, and rolls up from
  zero when the counter first shows. The value is in the text once, for screen readers and tests; the digits are
  drawn by CSS.
- The nav's highlight (its tint and bar) is one element that slides to the active item, changing into that
  item's section color as it goes.
- The header's logo is alive: its dot breathes while the stream is live, an arc sweeps its ring while a tick runs or
  one Tick now asked for is starting, and a ripple leaves it when a new tick appears.
- The theme toggle reveals the new theme as a circle growing from the button, in 420ms, and its new icon spins in.
- Skeletons shimmer: a light passes over them.
- Fun moves as its code says, within these rules. A cleared item's fold is the one animation that fills forwards:
  the row is let go once it has played.
- A toast rises in from below and fades out.
- What floats over the page fades in, growing a little from where it opens (`animate-float`): a dialog over its
  fading scrim, a popover, a hover card, or a tooltip from its trigger's side, and fades out quicker. A sheet slides
  in from its edge. A menu only floats in (`animate-float-in`): it goes at once on a choice, so the focus the choice
  moves is not left waiting on it.
- Only `running` runs pulse.
- Every animation rests on the frame a still page shows (its last, or for a loop its first), so a screenshot with
  animations frozen is the page at rest.
- Everything above is off under `prefers-reduced-motion: reduce`: the theme swaps instantly, values and rows appear
  in place, pulses and ripples are hidden, and fun holds still. New motion goes inside a
  `prefers-reduced-motion: no-preference` block or a `motion-safe:` variant.

## No layout shift

- `scrollbar-gutter: stable` on what the page scrolls in (`page-scroll`), so a page that grows a scrollbar does not
  move.
- Async content gets its space before it arrives: a fixed width for readouts, a minimum height for panels. A panel
  holds that height only while its read is pending: read, it is as tall as what it holds, and a transcript with no
  events is its header alone.
- A skeleton (`PanelSkeleton`) shows only while there is no data at all, and only while the read is pending: once it
  has failed, a Notice takes its place at its height (`PanelLoading`). A refetch or a stream update keeps what is on
  screen.

## Themes

Light, dark, and system, stored in `localStorage` under `canopy-theme` (absent means system) and synced across tabs.
The blocking script in `index.html` sets the `dark` class, `color-scheme`, and `data-theme` on `<html>` before first
paint; `src/theme/store.ts` keeps them current afterwards. Change one, change both: `theme-script.test.ts` runs the
inline script and checks it against the store's key. Each theme's palette is kept the same way, as JSON under
`canopy-palette` (`src/theme/palette.ts`), and set on `<html>` by the same script; a palette picked for the theme
shown is revealed as a theme is (Motion). The key that sends a reply is kept the same way, under `canopy-send-key`
(`src/lib/send-key.ts`), each list's order under `canopy-list-order` (`src/lib/list-order.ts`), and each fun setting
under a `canopy-*` key of its own, all synced across tabs.

## Primitives

Every list and detail page is built from the same few pieces, so a new page lines up with the others without anyone
measuring. A page that needs something they do not offer extends them here first; it never builds a row, a field
list, an empty state, or a skeleton by hand. The components page (`/components`, over the mock journal alone, linked
from nowhere) draws each one live in its sizes and states, so a change to one is seen whole there and in its screenshot;
a primitive a page can show without data of its own adds itself there.

**A layout step inside the content pane is a container query, never a viewport breakpoint** (`@container` on the
pane's part or its `Panel`, then `@min-[…]:` or a named size). The rail takes 13rem from the pane at `lg`, so a step
keyed to the window is tightest just past it: going from a 1023px window to a 1024px one makes the pane about 150px
narrower. A step comes in once the pane has room for it and what it sits beside at full size, so nothing narrows as
the window widens: the worktrees counters stand four across once each gets 11rem, else two by two, never three and
one. The wide screens' second column (Shape and space) stays the window's, at `2xl`, where the rail is whole either
side.

- **`ListRow`** (`src/components/rows.tsx`): a list's row, a CSS grid in its kind's columns (`ROW_COLUMNS` in
  `src/lib/rows.ts`). Each column is a named grid line and a width; every one is fixed but one free column, which
  takes the rest and cuts its text to fit, so every row of a list lines up whatever its cells hold. The free column
  never gets under 8rem: it holds the row's name, a ticket's title, which never vanishes. A kind whose name needs more
  sets a floor of its own (`free`): a worktree's branch, 12rem, room for `agent/ABC-104-retry-queue` whole. A column
  may be fitted instead of fixed (`fitted`): its list sets its width to the longest of its cells, all in monospace, so
  its rows still share it and line up (`fitColumn`), and the room it does not take goes to the free column; its most
  is what the tiers count. The PR list's `pr` column is one, at most 11rem.
  **A narrow list lets columns go**, in the order its kind gives them (a third entry in `ROW_COLUMNS`, 1 first), so it
  fits its panel wherever the panel sits: a narrow window, beside a ticket's thread. A column shows from the narrowest
  of Tailwind's container sizes (`ROW_TIERS`, `@sm` to `@4xl`) with room for it, the columns that go after it, and
  those that never do, the free one at its floor (`rowTiers`). The `Panel` is the container (`@container`), so a list
  goes by its own width, not the window's. The row's template at each size is a custom property, and a column left
  out hides the cell in its place (`rowLayout`); it lends its name to the next column shown, so a `RowLine` from it
  still has a place. Every column shows at `@4xl`, which a list in a 1280px window reaches. `index.css` lists those
  classes for Tailwind, since they are built at run time.
  The head line's cells fill the columns in order, so a cell that may be empty still renders (an empty `span`). What
  goes under the head line, a summary, its links, an earlier run, is a **`RowLine`** that spans from a named column to
  the row's end (`from="title"`), never a hand-computed indent: no `pl-[…]` in `src/routes` or `src/components`. A
  summary starts under the row's name: a ticket's title on the runs page, the run's id under its subject, a tick's
  id, a decision's action. What sits under a row outside it, a tool call's body, is a **`RowGrid`** of the same
  kind with a `RowLine` in it. A new list is a new kind in `ROW_COLUMNS`, its columns written out there. An age column
  is `6rem` and a cost column `4rem` in every kind (`AGE`, `COST`), so they line up from one list to the next.
- **`Fields`** and **`Field`** (`src/components/fields.tsx`): a detail page's field list, an `8rem` label column and
  the values beside it, the label in `panel-label` type and the value in prose or, with `mono`, in monospace data.
  The rows sit on their first baseline, so a label stays level with the first line of a value that wraps (a summary,
  a PR with its other reviews under it), and a label that wraps does too. A total cost is a `Field` (`CostTotalRow`).
- **A document** is long-form prose set to be read rather than scanned: a guide page (`GuideText`) and a plan
  (`.plan-doc`). It takes its type from three utilities in `src/index.css` and nothing else, so the guide and a plan
  read alike: `document-text`, the body, `text-base` on a 1.75rem line, a step up from the app's `text-sm`;
  `document-section`, a `#` or `##` heading, the page title's `text-xl` semibold; and `document-subsection`, a `###`
  or `####`, the body's size in semibold. Two steps of heading, so a section stands a quarter above the body and a
  subsection apart from it by weight alone; the guide's page title is its header's, so its body starts at a section.
  Code is set as everywhere else (`Code`, Rich text), a block on the raised surface. Its measure is fixed, 48rem at
  most (`max-w-3xl`) on both surfaces. The plan's style menu previews each style in its utility. What lays a document
  out, the guide's rules between sections or a plan's margin, is its surface's own; its type is not.
- **`ReviewsTable`** and **`RunsTable`**: review runs and runs, one row each, on every page that lists them. On the
  page of what they belong to, the columns that would repeat it go (`pr={false}`, `ticket={false}`), as a `ListRow`
  kind of their own (`own-review`, `own-run`). A run names the PRs it pushed to under its row, so on a PR's page
  `ownPr` leaves that PR out of them, as it does from `Decisions`. The reviews one request made of one commit, one per
  persona (DESIGN §31), are adjacent rows where the first of them falls (`requestGroups`), with no hairline between
  them: each keeps its own verdict, draft chip, cost, and age, and after the first, the free column says only
  `as skeptic`, at any width, in place of the PR and commit it shares, its ticket's cell empty. Rows, not a nested
  card: the request is one entry read down its personas. A run's model, in its row as in its Run panel
  (`ModelsField`), takes no status color: a run the model asked for served none of reads `asked Y ≠ X`, asked first,
  the served model in `foreground`, and one it served beside another marks only the other; `sameModel` takes `X@v`
  asked and `X` served alike. Until its session is read the row says `model unread` (`UNREAD`), muted, why in its tip,
  and a run with no session names no model.
- **`Empty`** (`src/components/panel.tsx`): what a list or page says when it has nothing to show, in muted text, in two
  sizes: `row`, where a panel's list would be, as its one row; `panel`, a page's main panel, centered with room
  around it, as one sentence whatever links or commands it holds. Its words are `no X yet` and one clause on why or
  what to do (`no runs yet: the overseer starts one when it is due`); `now` for what comes and goes rather than `yet`
  (`no open findings now`). A config key or a command in it is `Code` (`capacity.max_chores`); a next step the UI can
  take itself is a link, or an inline button as Tick now is, never the CLI command that does the same. A search that
  finds nothing says so; a page whose subject is missing (a 404) says why. An error is never an `Empty`, and never a
  red sentence in a panel: it is a `Notice`, which names a refusal's guard and sets its `code` spans as code, as an
  attention item's detail is. A page whose read was refused (a 409) shows its `Notice` in its main panel.
- **`ListPanel`** (`src/components/list-panel.tsx`): a detail page's supporting list (runs, reviews, decisions) in its
  panel, headed by its noun, its `OrderToggle` from two rows, and its count. With no rows it is its header alone,
  counting `0`, with no `Empty` under it and no hairline under the header: the count already says it, and an empty
  list should not take a panel's worth of the page. A list the page's subject can never have is left out, not
  counted: a PR canopy only reviews has no ticket, so no runs. A PR's and a ticket's pages are built from it; the
  other detail pages keep their `Empty` rows until they move to it, one rule for every page rather than one per page.
- **`None`** (`src/components/none.tsx`): what a field or a cell holds when it has no value, `none` in muted text in
  its place's own type, never a sentence of its own. With a reason, the reason follows a colon; in a column too narrow
  for it (`brief`), the reason is on hover. One phrase per concept: a summary, a branch, a PR, a session, or a tick's
  output that was never recorded is `none`; a PR canopy only reviews has as its ticket `none: canopy only reviews it`
  (`NO_TICKET` in `src/lib/words.ts`). A list with no rows is an `Empty`, not a `None`.
- **A model** (`src/lib/models.ts`) is named one way on every page: its id, `provider/model@variant`, in monospace, a
  variant after `@` (`withVariant`), never `at high`. A dense list, a runs list or a cost split, drops the provider
  (`modelNames`), unless two of its models would then read alike, and gives the whole id in the tip; a picker, a field,
  or a table of models names it whole, as a gateway (`github-copilot/`) can serve its maker's models under the same
  name. No model is muted sans, never monospace, since it is no id: `runtime default` (`RUNTIME_DEFAULT`) where nothing
  sets one; `unread` (`UNREAD`) for a run whose session canopy has not read, why in its tip; and `None` with why for one
  read that named none. A model takes no status color, but one the runtime no longer lists, `status-failed`, since it
  refuses the next run.
- **`Input`**, **`Textarea`**, and **`SearchField`** (`src/components/input.tsx`): every text field, on
  `surface-raised` with a hairline and the accent's focus ring. An `Input` is one height everywhere, `h-9`, a form's,
  beside its default buttons; a number is an `Input` too. A field to search or filter with is a `SearchField`: a
  magnifier, the field, what it says at its end (a count), and a ghost clear button while it holds text, in the place of
  what sits there empty (the rail's keycap). Its two sizes are the rail's and a list filter's (`h-8`, `text-sm`) and a
  panel's own line of data (`sm`, `h-7`, `text-xs`). No page builds a field by hand.
- **`MarkdownField`** (`src/components/markdown-field.tsx`): a field the operator writes to an agent in, in the Markdown
  `RichText` draws and nothing more (`src/lib/markdown-edit.ts`): bold, code, a heading, the two lists, and a code block
  from a `Toolbar` under the text and ⌘B and ⌘E, the rest typed, so what is written reads in the thread as it did in the
  field. It is one box, the field's look, the text then the toolbar under a hairline, so Tab reaches the text first. An
  edit goes through the browser, so its undo takes it back. Three sizes, each growing with its text and then
  scrolling: `line`, one line high, beside a form's `Input`; `default`, a reply's few lines; `tall`, a long brief. Its
  preview is `tab`, Write and Preview at the toolbar's end, the preview at the text's height; `live`, beside the text
  once the box is `@2xl` wide, under it before; or `off`. A label names it through `htmlFor`, never around it. A field
  takes it when what it sends is later drawn by `RichText`, so the preview tells the truth: a reply, a task's text, and
  a feedback plan's words, which land in a conversation, and a comment or reply on a plan, which its card draws so. One
  drawn as plain text (the notice, a review request's notes) stays a `Textarea` until it is drawn so.
- **`PanelSkeleton`** (`src/components/panel.tsx`): what a panel shows while its data has not arrived at all, `rows`
  shimmering bars, each shorter than the last. It takes the minimum height its content will, so nothing moves when
  the data lands: `min-h-72` for a page's main panel or a list that runs long (tickets, runs, ticks), `min-h-40` for
  a list that holds a few (the attention list, the chores, a pool's slots).
- **`PanelLoading`** (`src/components/panel.tsx`): a skeleton while a read is pending; a Notice once it has failed.
  A page's main panel shows it while its data is `undefined`, given the query: until the read fails it is the
  `PanelSkeleton`, and after, at the skeleton's minimum height, a `Notice` saying why (`src/lib/read-failure.ts`: the
  server's status and words, or that canopy did not answer and `canopy loop` serves the page) and a ghost `Read again`
  that refetches it. A 404 or a 409 is the page's own state, handled before it. The query client retries a read once,
  so a failure shows within about two seconds, and nothing refetches it after but the button or the stream. A page of
  many panels over one read (Spend) shows it once, in its first panel, and leaves out the rest.
- **`PanelFooter`** (`src/components/panel.tsx`): a panel's foot, the mirror of its `PanelHeader`: its actions under a
  hairline, default-size buttons in a line, then the line that says what they will do, then what one did (`Notice`).
  A `sticky` foot stays at the bottom of the page while its panel scrolls over it, as a sticky header stays at its
  top, opaque on `surface`; the page's scroll padding (`.page-scroll` in `src/index.css`) keeps what Tab moves to and
  what is scrolled into view above it. A bar of actions never floats in a box of its own: it is its panel's foot.
- **A draft's card** (`DraftCardFrame`, `src/components/draft-card.tsx`): text canopy holds that would post as the
  operator on a PR, a thread's reply (`DraftCard`) or a review's comment (`DraftCommentCard`, `NewCommentCard`,
  `ReviewPointCard`), is one card: `surface`, a `status-blocked/40` border while it waits on the operator, a header of
  its `panel-label` and what names it, its text, then its verbs in a row under it, `sm` buttons with the CLI's command
  on hover, `Edit` outline (`EditVerb`) and `Drop` ghost (`DropVerb`). `Edit` opens `DraftForm`: a `Textarea` with its
  count against 4,000, `Save` disabled past it or while the text is not one the draft may hold, and `Cancel`.
- **A table of figures** (a chore's spend, the Spend page's) is a `table` across its whole panel where its rows name
  something that wants the room (Landed, By ticket); one with a short name and a few figures (Delivery, Checklist, a
  chart's days, who reviews) sizes to its content at the panel's left, so a row reads in one glance. Its column heads
  are in `panel-label` type, its figures right-aligned readouts. A row head that names something (a ticket, a tool) is
  its name in medium weight at the table's size, as `TicketTitle` sets a ticket's title, after its reference (a ticket's
  key, a PR) in its monospace link; a day or a group of ticks is in the table's own type. Its panel's header repeats
  none of its rows. Rows in groups (the checklist page's items, by repository; Health's sorts, by kind) stay one table,
  so their columns line up: a `tbody` per group, headed by a row whose `rowgroup` cell names it in the table's own
  type, medium weight, with the group's own figures in its columns where it has them (a kind's runs and spend).
- **Readout tiles** (`ReadoutTiles`, `src/components/readout-tiles.tsx`) are a report window's headline figures: its
  sums, not a count of what is now, so they are not `Counter`s. Each is a `panel-label` name over a `readout text-xl`
  figure in a `dl`, what it counts in the name's tip, and, when the page has the window before's figure, a muted line
  under it saying how it moved (`+3 on the 7 days before`, `same as ...`), in `status-failed` only where the page says
  which way is better and it moved the other (a rising failure rate; never rising spend). A row of them sits under a
  report's description (Health, CI, Reviews, Checklist); the Spend page's Totals are a grid of them in their panel,
  whose cells are too narrow to name the window before under each figure, so a line under the grid names it once. A kind
  that spent nothing is no tile of a dash but a muted line under the grid (`No dry runs.`), so the tiles hold what was
  spent. A figure still being read holds its place. A `Counter` stays the attention and worktrees pages' count of the
  present, with its state's color.
- **A bar in a cell** (`CellBar`, `src/components/cell-bar.tsx`) draws a column's figure as a share of its largest
  (`barPercent`), where comparing the rows is the point: spent by month, by ticket, and by model, the bytes a tool
  returned, a check's failure rate. The figure, at a fixed width so the bars start at one edge, then a 6px rounded bar,
  64px long at least so a narrow column's still compares, on `surface-raised` filled in `muted-foreground`, or the
  series' own fill; never a state's color, but for a failure rate (Health's failed share of a kind's runs, CI's
  checks), in `status-failed`, a share of the whole rather than of the column's largest: it says what is broken. It is
  the eye's, `aria-hidden`.

## Charts

What every chart follows (`src/lib/chart.ts`), so a new one needs no rules of its own; each chart's entry under
Patterns names what is its own.

- **Bars from zero**, in fill tokens of their own (Tokens), never a state's color. The plot's top is the peak and a
  quarter more (`HEADROOM`), so the tallest bar stops short of the edge, and the peak's value sits over its bar as a
  `readout`: the scale reads without hovering. Over the first or last bar it is flush with the bar's outer edge, since
  it is wider than a narrow bar and would overhang the chart's padding.
- **A bar's width is capped**, the row centered, so a sparse window draws narrow bars rather than slabs.
- **Stacked segments are 2px apart**, the surface between them, and any segment with a value is 2px tall at least, so a
  sliver still shows; the top segment's corners are rounded.
- **The axis** names its marks by one helper, `axisStep`: every mark of a short axis, every fifth of a long one, back
  from the last, so the latest is always named, and fewer where names that often would touch. A name is centered under
  its bar and may be wider than it; it is never cut to fit.
- **The legend**'s words are `muted-foreground` beside a swatch of the fill.
- **A value is on hover**, with its unit: `$1.50`, `30.2k sent`.
- **No data is `Empty`**, saying what there was none of: never an empty plot under a legend.
- **A table holds the same numbers** wherever the chart is `aria-hidden`, for a screen reader and for a value too small
  to see. Under a day chart it folds (`ChartTable`): a `Disclosure` with its rows on its line, `Show 7 days as a table`,
  closed on arrival, the table still in the page for a screen reader while it is. The legend says what each series
  counts, in its name's tip, so the table's heads are plain.

A measure over time (`TrendChart`, `src/lib/trend.ts`, the system resources page's graphs) is a line, not bars: 2px
in the accent with round joins, the area under it the accent at 10%, from zero on a 1px `border` baseline, broken where
no reading was taken rather than bridged. Its top is a capacity where the measure has one (all the memory, a disk's
size) and the peak with `HEADROOM` where it has none. A threshold it is read against (the cores, the tick's floor) is
a 1px `muted-foreground` line at 40% with its name at its right end, drawn only while it is under the top. Its label and
its latest value head it, `now · peak` after the value; the pointer snaps a crosshair and an 8px accent dot ringed in
`surface` to the nearest reading, whose value and time stand in the latest's place. The plot is `aria-hidden`, and a
screen reader hears its latest value, peak, and low in words in place of a table.

The context chart differs where it must: its bars are its controls, each named for its call on hover and to a screen
reader, so no table repeats them; a call's added part is 1px at least, since it is one of two segments and never a
sliver beside four others; and its axis names short call numbers without measuring, every one up to twelve.

## Patterns

- **Lists are rows in a panel** (`ListRow`), divided by hairlines, and every row reads in one order: its **state**,
  where it has one (a run's dot and word, a review's verdict, a tick's status, a ticket's run, a note's standing), so
  the left edge of a list answers "is anything wrong?" without a word read; its **own id** (`run:41`, `review:4`,
  `tick:2`, `memory:3`), in the same place on every page; **what it belongs to** (a ticket's key, a PR); the **chips**
  that describe it (a run's kind, a review's impact, a ticket's phase and access, a PR's phase), each in a fixed
  column; then the **free column**, a title or what fills the rest; and after it **only readouts** (counts, cost,
  tokens, age), right-aligned, each as Readouts (below) says, age last and cost just before it. A chip never follows
  the free column: there its place would shift with the title's length, out by the readouts, far from what it
  describes. A list without a state (decisions, findings, search hits, a transcript) leads with its id or its subject.
  On its subject's page a list keeps the order and leaves out what the page is (`own-run`, `own-review`).
- **Readouts** say an age, a moment, or a cost one way on every page (`src/components/age.tsx`, `timestamp.tsx`,
  `cost.tsx`). An age is `Age`, the CLI's largest whole unit with the local time in its tip, in the variant for what it
  measures: `ago` for a moment (`3m ago`: a message, a decision, a search hit, a ticket's or PR's last activity),
  `span` for something that runs (`for 3m`, then `ended 3m ago`: a run, a review, a tick, a chore run, a held
  worktree), and `bare` for how long an item has stood open, where its place says so (`3m`: an attention item, an open
  finding, the rail's runs, the oldest question). The header's tick is the one exception: `3m ago` once it ended, so
  its line stays short. A moment shown whole is `Timestamp`, the local `Oct 8 10:30` with the ISO time the journal
  keeps on hover, beside its age on a review's page, and in a run's, tick's, or chore run's `when` field, which sets
  its end after it, the time alone on the same day, how long it ran (`lasted`, the age's units), and its `span` age;
  a raw ISO string is never shown. Every time of day, hovered ones included, reads on the clock picked in Settings
  (`useClock`): 24-hour or `10:30 AM`, with the zone or without. A cost is `Cost`: `$0.42` as a readout, its
  dollars grouped by thousands (`$1,234.50`, `costText`, rounded to the cent as the CLI rounds), or a dash when
  nothing reported one, `none reported` on hover; never formatted in place, a hat's price included.
- **A fact on hover is a tip** (`Tip` in `src/components/tip.tsx`, on the `Tooltip` wrapper): a word's CLI spelling,
  an age's local time, a commit's whole hash, every one of a `+N more`. A `title` reaches neither the keyboard nor a
  touch screen, so a fact a list keeps out of its text is a `Tip`: it opens on hover, after half a second so a pointer
  crossing a list opens nothing, on the keyboard's focus, and on a tap, and closes on Escape, on leaving, or on
  another tap; what it wraps becomes a stop for the keyboard. Text cut to fit is **`Clipped`**, the whole in its tip
  while it is cut and only then, so a title that fits is no stop. A tip is `text-xs` on `surface` with a hairline, no
  shadow and no motion, as a menu is, and the fact is in monospace where it is the CLI's spelling. Inside a link, a
  button, or an element with a `title` of its own, a tip is the plain `title` it was: the keyboard stops on the control
  already, and a stop inside it would be a control in a control. What the operator acts on is in the text, never only
  in a tip (the `canopy grant` command under its button). What a report's column or figure counts is a tip too, on its
  name (`Hinted`), with a muted dotted underline saying there is one. A `title` that explains rather than informs, a
  button's hint, stays a `title`.
- **A link's page at a glance is a hover card** (`HoverCard` in `src/components/ui/hover-card.tsx`): more than a tip
  holds, a few rows of what the page it opens shows, as each header readout shows its page (`ReadoutCard`). It opens
  on hover after half a second, as a tip does, and on the keyboard's focus, and stays while the pointer moves onto
  it; a tap follows the link. Like a tip it is on `surface` with its edge and floating shadow and no motion, its rows
  `text-xs` under `panel-label`s. Nothing in it is found only there: it is a preview of the page, never a place to act.
- **A list in time can be flipped**, oldest first or newest first, from its panel's header (`OrderToggle`): every list
  in time order, which is a conversation, a chore's notes, a transcript, the runs page and a ticket's, chore's, or
  PR's runs, a ticket's, tick's, or PR's decisions, the ticks, the tickets, the PRs, and the reviews and a PR's. The
  toggle is a ghost button before the count, an up-down arrow and the order it is in, in words (`newest first`); a
  click shows the other. A list sorted by each row's latest activity rather than by when it began, which is the
  tickets, the PRs, and the runs page, says so (`recently updated`, `least recently updated`, after
  GitHub's sorts): its first row may be its oldest, so `newest` would mislead. Each list starts in the order the
  server sends it and keeps the operator's choice for that list alone, wherever it appears: a conversation flipped on
  a ticket's page is flipped in the inbox too. It shows only when the list has two items or more. Search has none: its
  hits are each source's newest few, so flipped they would read as its oldest.
- **A list that grows without bound scrolls inside its panel** (`PanelScroll`) when other panels sit under it in the
  same column: a ticket's recent runs and decisions, a chore's open findings and recent runs, the spend page's days
  (past `15rem`, under its pinned column names, so a week shows whole and 30 days scroll). Past `28rem` the rows
  scroll under the panel's header, with a thin scrollbar, so the panels below stay in reach. The region takes focus,
  so the keyboard scrolls it too. A list that is its page's main content (the runs page, a tick's decisions) does
  not: the page scrolls instead.
- **A thread scrolls inside its panel too** (`ThreadScroll`): a ticket's conversation, on its page and in the attention
  item, and a chore's notes. Past 60% of the window's height (never less than `20rem`) the messages scroll between the
  panel's header and the reply form, so a long thread never pushes the form a page away. It opens at its newest end,
  the bottom oldest first and the top flipped, as a chat does, and keeps to it as messages and the working run arrive,
  while the operator is within a bubble's gap of it; scrolled away to read, it stays where they put it. A flip, or
  another ticket or chore, on its page or in the inbox, opens it at the newest end again.
- **The runs page is a row per subject** (`SubjectRunsTable`, `subjectRuns` in `src/lib/run-state.ts`): every agent
  canopy runs, a ticket's worker runs, a PR's reviews, and a chore's runs, in one list, so the operator sees where
  the sessions go and what waits on what. A subject's row is its latest run, which says where it stands, and under it
  `Show N earlier runs`, a `Disclosure` that opens the runs before it, newest first, each one line in the row's own
  columns (a `ListRow` of the same kind): its state, its id, its chips, the first line of what it said in muted text
  where the title is, cost, and when; the rest is on its run's page. A chore's earlier run is only its latest that
  ended, under one running; its chore's page has the rest. The head line reads the state, the run's id (`run:41`,
  `review:4`, or a chore run's `#2`), what it works for (the ticket's key, a review's ticket, the chore), its kind's
  chips (`resume (ci)`, `review`, `chore`), and in the free column the ticket's title, or a review's PR, commit, and
  verdict. What goes under it starts under the title. A ticket that asked, got its answer, and asked again is one
  blocked row, not two. The kind and state filters keep each other, and the state filter goes by each subject's
  latest run, as do the rail's working runs: a blocked run a later one followed waits on nothing. Under the page's
  description, a line counts what runs against each `[capacity]` limit as the harness counts it (`workers 2 of 2`,
  reviews among them, and `chores` apart), a full one in `status-blocked` with `full`: the next start of its kind
  waits for a run to end. A ticket's page lists its runs flat
  (`RunsTable`), since every row there is the same ticket's. A run's line of links names its first three worktrees,
  then `+N more worktrees` with every one in its tip, never `+1 more`, which would take the room the fourth's path
  does: a ticket across many repositories holds a slot in each, and its run's page lists them all.
- **A total cost** (`CostTotalRow`) is the last row of a ticket's Work panel and a PR's Pull request panel: the total
  as a `readout` (`costText`, a dash when nothing reported one), then, muted, what it counted
  (`over 3 runs and 1 review, 1 unpriced`; `countedText`), since the page lists only the recent ones.
- **The tickets list**: where the ticket stands (`TicketState`), the key, the phase (cut to fit, the CLI's spelling in
  its tip), the `public` or `private, started` chip, the title in the free column, and the age. Where it stands is the
  running run or `waiting on you`, each with its run's dot, else `done` or `open` with the dot of a run that ended so,
  so every row has a dot and the column is never blank. Narrow, the chip goes first, then the phase, then the age;
  where it stands, which says when the ticket waits on the operator, goes last. A run's list lets its cost go first,
  then its chips, then its age, then its id; a review's its cost, its impact, its ticket, its age, then its verdict; a
  tick's its tokens, its peak, its cost, its decisions, then its age; a PR's its phase, before its title is cut to a
  word, its age, then where it stands; a worktree's what holds it, before its branch is cut, since the branch names the
  ticket too, then its age. At half a monitor (an 820px window, a list about 44rem wide) a run keeps its age and a
  slot its branch. Money and tokens go before what names a row. Each kind's order is in `ROW_COLUMNS`.
- **The tickets board** (`?view=board`, `TicketBoard`): the tickets list's tickets, under its filters and order, in a
  column per stage (`BOARD_COLUMNS` in `src/lib/ticket-board.ts`), every column shown, an empty one saying `none`. A
  column is a well on `background`, its name an h3 with its count as a readout and its phases in the name's `title`;
  a card is on `surface`: its key and age, its title, then where it stands, its phase, and `private`. Done shows its
  most recent few and links to the done list. It only reads: no drag, since the loop moves a ticket. Past the panel's
  width the columns scroll sideways inside it, a focusable region; a `list`/`board` `ToggleGroup` heads the panel.
- **The tasks list**: where the task stands (`TASK_LOOK` in `src/lib/tasks.ts`, a run state's dot and color: `waiting
  on you` in blocked's, `queued` muted, else its latest run's status), `task:N` (opening its page), the repository,
  the text's first line in the free column, and the age since it was submitted; under the text, the first line of
  what its latest run said.
  The tasks waiting on the operator's reply come first, the rest newest first, so it has no `OrderToggle`. Narrow, the
  repository goes first, then the age, then where it stands. A repository picker (`?repo=`) narrows it.
  Above it, as the reviews page's `Review a PR` panel is, a `Submit a task` panel (`TaskSubmitForm`) on one line: the
  text in a `MarkdownField` one line high, with no toolbar, that grows as it is written (to `15rem`, then scrolls), the
  repository it runs in (`RepoSelect`, only with several, starting at the one the list is narrowed to, else the newest
  task's), the tracker project in monospace, and an outline `Submit` with its send keycap; under them one muted line
  says what a task may do, which a refusal replaces. On success a toast says what the CLI says and the form opens the
  task's page; the row arrives on the stream, never added by the page.
- **A task** (`/tasks/$id`) is one story: its title `task:N` and its text's first line, its description where it
  stands (in its look's color), its runs, and when it was submitted. Then the detail skeleton, with the story as its
  thread: a Conversation panel (`TaskStory`) whose oldest end is the operator's instruction, whole, as their own bubble
  (`task:4 you instruction via cli`), then its messages, each naming its run as `task:4#5`, which opens the run's page
  (`/tasks/$id_/runs/$run`, a chore run's skeleton, its task in the trail); no tick chips, since no tick reads them.
  It ends on the run working now, as a ticket's does. The panel's foot is its answer, as a ticket's is: the
  `ReplyForm`, then its stop (`TaskActions`) under a hairline. While a question waits, the form sits on the
  `status-blocked` tint under a line naming its message, one element either way, so what the form said stays as its
  reply clears the question. Stop asks once more (`Stop task:N`, `Keep it`), since a task has no start to undo it, and
  Stop now, while a run works, asks as a ticket's does; a task stopped while its run works keeps Stop now alone. A
  stopped task has no form. Its main content is the Report panel
  (`TaskReportPanel`), its newest run's report that left one, laid out read only through the plan's schema
  (`PlanDocument`), so it reads as a document and stays text; its header names the run and `edited`, its foot the
  file's path, and with none an `Empty` saying what comes next or why. Then What it left (`TaskLeft`): its repository,
  its branch, each run's pushed head commit (its run, then the short hash, the whole in its tip and copied whole), the
  draft PR, the tickets filed (`TicketLink`, with the run that filed each), a `None` with its reason for what it left
  nothing of, and under them one muted line saying all of it is throwaway until given a pass. Then its Runs, oldest
  first. Wide, the report takes the second column beside the rest.
- **The tickets filters** narrow the list two ways at once (`src/lib/ticket-filter.ts`). Where a ticket stands is the
  runs page's chips, in the Tickets panel's header (`?show=`): `open` (not done), `working` (a run on it now) and
  `waiting on you` (a question waiting), each with its run's dot, `blocked` (the overseer's phase for a ticket an
  open blocker ticket holds up, LOOP §7; no dot, since no run of it asked anything), and `done`. Under the header, a
  search field (`SearchField`, `?q=`) keeps the tickets whose key or title holds every word, in any case: the search
  page does not read titles, and in a list of a hundred tickets the operator knows the one by a word of its name. The
  list narrows as they type, each keystroke replacing the history entry, so Back leaves the page. A filtered count says
  `6 of 41`, and an empty result says which filter left nothing. Both filter the list the server sends, its 200
  newest by activity, not the whole journal.
- **The PR and review filters** narrow the pull requests and reviews lists as the tickets filters do
  (`src/lib/pull-request-filter.ts`, `PullRequestFilterBar`): under the header, a search field (`?q=`) keeps the rows
  whose PR, repository, or ticket holds every word (a PR's titles too, a review's commit), and beside it a repository
  picker (`RepoFilter`) of the repositories the list's rows are in (`?repo=`), shown while there is more than one. A
  review requested but not yet started has no repository until a tick reads it, so a chosen repository leaves it out.
- **Chips** (`Chip`) label a row with a fixed word: a kind, `private`, a reason. Never with journal text. A word
  the journal stores (a reason, an action, a kind, a phase) goes in as `word` and reads as words: underscores become
  spaces and an action's prefix takes a space after its colon (`worker failed`, `attention: needs reviewer`), while
  the CLI's spelling stays in its tip, so it can still be found in `attention.md` or typed into the CLI
  (`src/lib/words.ts`). A reason's or a phase's tip says under the spelling what it means, in a line
  (`src/lib/meanings.ts`, `meaning` on `Chip` and `Word`), so its tip opens even when the word needs no spelling.
  Outside a chip, a phase in a field or a list and a status in a header or a row read the same
  way (`Word`, `phaseLabel`); no journal word shows with its underscores. Journal text that is not a fixed word (a
  chore finding's id, `review.query`) and a count (`1 finding`) are muted monospace, never a chip. A chip with a
  long word in a narrow column cuts it to fit (`min-w-0 shrink`), the whole word in its tip, as the search page's
  labels do; none is stretched to its column. Its color is its `tone`, from the one map of them (`Chip` in
  `src/components/status.tsx`): its color's hairline at 40% over the same color at 10%, so it holds its edge on a
  selected row's tint; `plain` in `muted-foreground`, else the status color of the state it marks, `failed`,
  `blocked`, or `running`, or, for a feedback plan's proposal, that proposal's own hue (`ProposalTone`). No chip is
  colored by classes of its own.
- **A status on a detail page** (a run's, a chore run's, a tick's, a review's) is its description's first word
  alone; the identity panel's header names the panel and nothing else, so the state is said once. Of the two homes
  it had, the description was kept, as the smaller change: it is the page's line of state on every detail page, and a
  review's was already its description alone, since its panel leads with what it found (A review, below). A run's
  journal says `done` where a tick's and a chore run's say `ok`: each is the CLI's word for its own, kept as it prints
  it, and in a list's row both wear `status-done`, as a tick's `skipped` does (`tickState` in `src/lib/ticks.ts`).
- **A run state named in words** (a filter's chip, an empty filter's message) is the operator's: `blocked`, a run that
  asked, reads `waiting on you` (`RUN_WORD` in `src/lib/run-state.ts`), as the rail, the tickets list, and a
  question's chip say it. The URL keeps `?state=blocked`, and a run's own status in its page's header stays the CLI's
  word.
- **A ticket's title** (`TicketTitle`) follows its key, in medium weight, so it reads as the row's name and apart
  from what a run said under it; one line, cut to fit, the whole in its tip while it is cut. A ticket with none yet
  reads `untitled`, muted, so its cell is never blank, the rail's working runs included, never the run's kind in its
  place. A ticket's page heading sets the key in muted mono before it. Nowhere too narrow to show more than a few
  letters of it.
- **Counters** (`Counter`, `src/components/counter.tsx`) head the attention page (running, waiting on you, and
  attention; the spend is in the rail) and the worktrees page (working, held, needs a look, free, across every pool).
  The line under the value is cut to fit, and whole in its tip, since it grows with the workspace (`4 pools unread`).
  A line is state, never what every visit would say: Held's names what holds its slots (`1 in use · 1 canopy-sync`).
  Nor what another counter or the nav already says (One home per fact): on the attention page only Waiting on you has
  a line, the oldest open question's age (`oldest 9d`), since it has no other home. Running's would count the runs
  waiting on you, which is the next counter's value, and Attention's would split the list, which the nav's badge does
  on every page; so neither has one, and `waiting on you` is said once there outside the rail and the nav. A counter
  with no line of its own shows none.
  A counter counts what its line lists, and a line that splits the count names only its parts there are: Needs a look
  adds dirty slots, broken ones, and unread pools (`needsLook`), so one of each dirty and unread reads `2` over
  `1 dirty · 1 pool unread`, never a `0 broken` among them.
  Each is a label, the value, and at most one line under it, with a 2px top rule in the state color it counts:
  `status-running`, `status-stopped` for held, `status-blocked`, `status-failed` while something is broken. The
  same color washes down from the rule at 12%, fading out by 70% of the counter's height; a plain counter has none.
- **The spend chart** (the spend page) follows Charts: a bar per UTC day, the series stacked bottom up in `SERIES`
  order, each segment its series' share of the day, the whole as tall as the day's share of the chart's top. Idle
  overseer spend sits on the baseline under the rest of the overseer's, a lighter shade of its hue, so the two read as
  one; at real costs it is a sliver beside a worker's, so its trend across days is read from the table, not the bars.
  A day with no cost is a 1px `border` stub on the baseline, so it reads as nothing spent, not a column gone missing.
  Each series has one name, in the totals, the legend, the table, and a bar's hover (`SERIES`), with what it counts on
  the name's hover: `overseer` is the live overseer's whole spend, idle ticks' included, as `canopy spend` counts it,
  and `idle ticks` the part of it idle ticks made, drawn under the rest. So the totals and the table say the overseer's
  whole, and a bar's hover says its day, then each series' cost, `overseer $1.00 (idle ticks $0.25)`. The page's
  description is the window's state, `$10.51 over 7 days · 2 tickets done` (`spendLine`); what the page shows on
  every visit is its title's help. The chart is `aria-hidden`: the table folded under it (`ChartTable`), newest day
  first, holds the same numbers for a screen reader, each a `Cost`, every cell after the first `pl-3` from the one
  before, and, opened, scrolls past a week, sideways when the pane is too narrow for its columns. A week names every
  day on the axis; 30 days every fifth, back from today, or, picked from the `by day` / `by week` control beside the
  panel's label (`?pitch=week`), a bar per local ISO week, named by its Monday as the first-call chart's are, a part
  week at either end. A window where no run reported a cost is one `Empty` line in place of the chart, its legend,
  and its table; the totals then leave out what reported no cost while no run ended, and the Ticks panel idle ticks'
  share while the overseer spent nothing. The window is a segmented control (`WindowToggle`) in the page header's
  controls, as on every report, so it is in one place whatever the page and however long it is; kept in
  `?days=`. By model and By tool sum each model's or tool's rows over every kind under `all`; the
  runs page's kind filter in each one's header keeps one kind's (`?model_kind=`, `?tool_kind=`), and offers only the
  kinds the window has rows of. A window switch keeps both filters. By model's ids link the runs page's runs on the
  model (`?model=`), with the kind shown (`?kind=`, `RUNS_KIND`: a plan run is a worker run there); one the runs page
  lists no run of by model, the overseer's alone, is plain, why on hover. The runs page's model filter is always
  offered, a picker of one (`ModelFilter`, below).
- **The failures chart** (the health page) is the spend chart's (`DayChart`), a bar per local day of the runs that
  failed, stacked by kind in `HEALTH_SERIES` order in each kind's spend series fill, its peak's count over its bar. A
  bar's hover says the day's failures out of its ended runs, and the table under it holds each kind's failures with
  the day's failed and ended runs, since a failure's weight is its share. A window where nothing failed is one `Empty`
  line. Its window, a week or 30 days, is the same segmented control as the spend page's (`WindowToggle`), in the
  page header, kept in `?days=`.
- **The red checks chart** (the CI page) is the same `DayChart`: a bar per local day of the red check runs, a series
  per check the server names apart, by rank in the check fills, and the rest summed as `other` in `check-other`, the
  legend and a table of the same numbers under it. Its window is the health page's.
- **The green-first chart** (the CI page) is the same `DayChart` over it: a bar per local day of the PR heads first
  checked, those green first time at the bottom in the accent and the rest in `check-other`, so a bad day is a short
  accent; the day's rate on hover, the legend and a table of the same numbers under it.
- **The first reviews chart** (the Reviews page) is the same `DayChart`: a bar per local day of the first reviews that
  arrived, stacked by wait in the wait fills, the quickest at the bottom, the day's median on hover, the legend and a
  table of the same numbers under it. Its window is the health page's.
- **A table of PRs** (`PullRequestTable`, `src/components/pull-request-table.tsx`) is a report's per-PR table: the PR
  with its unit's phase, its ticket, then the page's own figures. The spend page's By pull request, the CI page's
  time to green and flaky kicks, and the Reviews page's By pull request use it.
- **The first-call chart** (the spend page's First calls by week) follows Charts but where a rate needs otherwise: a
  bar per local ISO week of one kind's series, in the kind's spend fill, as tall as the share of the week's first calls
  the cache served, its top the whole and `HEADROOM` over it, so the axis means the same in every window, and every
  bar's rate over it, since there are six at most and the eye compares neighbours. A week whose runs recorded no cache
  read is a stub with a dash. A week whose runs used a runtime version or definitions snapshot the week before's did
  not has a 1px `muted-foreground` rule down the gap before its bar, and a line under the chart names what it used, in
  `canopy spend`'s words, so a screen reader hears it beside the table of each week's runs, median first call, and
  rate. The axis names each week's Monday. The kind filter has no `all`, since kinds' prefixes do not sum
  (`?first_kind=`, the first kind with a week by default), and the chips over the chart pick the kind's runs, a
  chore's, or a model's (`?first_series=`); a kind switch goes back to all its runs.
- **A slot strip** in a pool's header: one 10px square per slot, in slot order, in the worktree state's color, an
  idle one hollow. The counts beside it say the same in words, so the strip is `aria-hidden`. A pool of many slots
  wraps its squares onto more lines, sharing the header's room with the pool's root, never past the panel's edge.
- **A slot is one line** in our state words, never treehouse's (its word is in its tip, as the path is in its
  number's). An idle slot shows its state and number alone, muted; only a note or an unreadable branch takes a second
  line, from the holder's column. A dirty slot's note, in `status-blocked`, says what it blocks (the pool never reuses
  it and counts it busy) and what clears it, since it is the slot most likely to sit there unnoticed. The branch and
  the processes treehouse found share the free column, each cut to fit with the whole in its tip: an agent can start a
  dozen, and the line still ends at the age. A pool treehouse could not read says why as a `Notice`.
- **Idle slots fold**: three or more in a row (`IDLE_RUN`, `slotGroups` in `src/lib/worktree-state.ts`) are one line,
  their state and then `Show 37 slots, #4 to #40`, a `Disclosure` (as a ticket's earlier runs are) that opens each
  slot's own line under it. A pool of many slots is mostly idle ones, which say nothing but their number; folded, those
  with work in them stay in reach. One or two in a row show as they are, since a toggle would save no room.
- **The worktrees filter** is the runs page's, by worktree state, in the Pools panel's header before Read again:
  `?state=` keeps the slots in that state and the pools with one (`poolShown`), under `broken` the pools treehouse
  could not read too, since Needs a look counts them. A pool's header still counts all its slots. The page's
  description is the pools' state, `3 pools · 7 slots · read 4s ago` (`poolsLine`): read on a timer, the page says how
  fresh its read is. What the page shows on every visit is its title's help. Idle slots fold as
  they lie in the whole pool, so a filtered line never spans a slot in another state.
- **The attention list is an inbox**: one list, most severe first, beside the selected item while the page is at
  least 48rem wide (a container query, `@3xl`). Under that, on half a monitor, the list and the item take turns, each
  the page's whole width: the list shows until an item is chosen, which opens in its place with `Back to the list`
  (a ghost button with a left chevron) as its first stop, where the focus goes, since the row went with the list; back
  on the list, its row is chosen and focused. An item the URL names opens so too. A reply that answers its item
  (`awaiting_reply`, `untrusted_review`) moves on: the next item that waits on the operator's answer and is not
  answered yet, after it in the list and then from the top (`nextWaiting`), is chosen and its row focused, the list in
  view, and a toast says what the reply did, since the form that said it goes with its item; the row it left keeps
  its `answered` chip. With nothing else waiting the item stays, its form's line saying what the reply did. Severity
  (`src/lib/attention.ts`): broken work first (a run's `crashed`, `unpushed`, `unknown_result`, `worker_failed`,
  `attempt_limit`, `chore_failed`, the review reasons, and a run refused its model, `model_missing` and
  `model_list_failed`, which only the operator clears), then what waits on the operator's answer (`awaiting_reply`,
  `untrusted_review`, `plan_review`), then every other reason, then chores' findings; within each, the item open longest
  first. Settings can hide the findings, in this browser alone (`useAttention`): the list, its counter, and the nav's
  badge leave them out, and a muted line above the list counts what it hid, so a hidden finding never reads as none.
  A row reads as an inbox's: its reason, subject, and age, then its ticket's title (`TicketTitle`, semibold) when
  it is about a ticket, or its task's text's first line when it is about a task, as a message's subject, then its
  detail, muted, as the preview; the selected item's head puts
  the title, semibold, after the key. A reason chip takes `status-failed` or `status-blocked` for the first two, plain
  otherwise. A finding's reason is its id, the agent's text, so its chip says `finding` and the id follows its chore in
  muted monospace. An item's detail is the harness's line, with its `code` spans set as code and nothing else read
  (`InlineCode`), but for a GitHub PR's address, which is a `PullRequestLink` (its name alone in a row, which is a link
  already), so a detail names a PR as the rest of the page does, and a run named as `canopy show` reads one, `run:40`,
  which is a `RunLink`. The CLI's `answer with canopy reply KEY` is left off the end of a question's detail: the page's
  reply form is the answer (`shownDetail`). The list is Attention, as the page and its counter are; what waits on the
  operator's answer is `waiting on you` wherever it shows: the counter, a question's chip in a conversation, the tickets
  list, and the rail. The selection is `?item=<id>`; with none, the most severe item about a ticket.
- **An empty attention list tells never started from all handled** (`EmptyAttention`). Before the journal holds any
  ticket, the page is the first step, an `Empty`: `no tickets yet: give one your queue label in the tracker, or start
  one privately on Tickets, then Tick now`, with Tickets a link and Tick now the header's button inline, since an
  inbox that was never filled is not one emptied. Once there was work, the empty inbox (Fun) is the reward.
- **The attention detail: the reason picks the first block**, under the item's head, what the reason asks of the
  operator (`ask` in `src/lib/attention.ts`), so the action it calls for is never buried under louder controls about
  something else. A run that broke (`worker_failed`, `crashed`, `unpushed`, `unknown_result`, `attempt_limit`): the
  ticket's latest run as a `RunsTable` row (its state, `run:N`, what it said, its cost), then the grant when it is stuck
  at a limit, so why it failed is read and another try allowed without leaving the page. A PR that waits on someone else
  (`needs_reviewer`, `ready_to_merge`): the PR's `LinkOutButton`, the item's action, its other mention in the head plain
  text, so the PR is one tab stop. A wait on the operator's answer (`awaiting_reply`, `untrusted_review`): the reply
  form is the action, and a question's head names it, `Waits on your answer to message 5, asked 3m ago`, rather than
  saying it, since the conversation holds it, marked `waiting on you` (One home per fact). A plan (`plan_review`): the
  plan's card (`PlanCard`, `bare`, its parts in the item's panel), with `Approve` and `Open plan`; a feedback plan's,
  which shares the reason and is told apart by its detail or its ticket's `feedback_plan`, a line naming the plan, its
  PRs, its items, and whether it is stale, with an outline `Approve it on org/repo#N`, a router link to the PR's page at
  `#feedback-plan`, where it is approved. A running run's question (`run_question`): its head names whose question
  it is and when it was asked, `Waits on your answer to run:41's question, asked 3m ago`, and under it the question
  as the run's page draws it (`ProgressQuestion`), each option a button that answers by letter; a toast says what the
  answer did, since the item leaves with it, and a worker's ticket's conversation follows, as a plan's does. Memory's
  items
  (`memory_proposal`, `lesson_review`, `lesson_wrong`): the proposals or lessons they name, with their verbs (above).
  Replies a run drafted (`drafts_waiting`): an outline `Read the drafts on org/repo#N`, a router link to the PR's page,
  where they sit on their threads; for a ticket's own draft, which names no PR, its waiting drafts (`TicketDrafts`,
  `bare`). A review's draft (`review_waiting`, `review_unsettled`): an outline `Read the draft of review:N` (`See`
  for one unsettled), a router link to the review's page its detail names, in place of the PR's review limit. A task's
  (`awaiting_reply`, `task_ticket_unrecorded`): named `task:N` (`TaskLink`) and its text's first line, as its row is,
  a question's head as a ticket's, then an outline `Answer on task:N` (`Open` for the other), a router link to the
  task's page, which holds its question and its answer, never the `canopy` commands its detail names. A ticket's run
  refused its model (`model_missing`, `model_list_failed`): the ticket's models (`TicketModels`), as its page shows
  them, the runtime's list read fresh from the runtime as the item opens, so the model it no longer lists is
  marked already. An item about nothing the page shows whose detail names a `canopy` command to run (`repo_missing`),
  or the overseer's or a chore's run refused its model, `canopy models`: the command, `Copyable`, and nothing to
  answer. A broken run's item shows any limit it is stuck at (below) under its run, as
  what it asks for. A ticket's item then shows its answer (below): its conversation, the reply form, and on the
  reasons above the ticket's own verbs (Start or Stop, Forget) and any other limit as a quiet row under the reply,
  Start and Stop as ghost buttons; on any other reason the verbs and the limit lead, under the head, as what it asks.
  Any other item about a PR no ticket owns shows its review limit; a chore's item (a finding or `chore_failed`) shows
  the chore's notes and the note form, and a finding a ghost `dismiss` beside its age (`useDismissFinding`) and, in
  place of its detail, the finding as its chore's page has it (`ChoreFindingText`): the title whole, then what it says
  of itself, then its link on its own line, where the item's detail runs title and link together; an item about none of
  them shows its detail and nothing to answer. The page keeps no list of the runs working now: the rail's, on every
  page, is the one, so one count of them shows at a time.
- **The answer** (`TicketAnswer`, `src/components/ticket-answer.tsx`) is where a ticket is answered, one component on
  its page and on its attention item: its conversation, the reply form right under it, then the ticket's verbs and
  any limit it is stuck at (`TicketVerbs`), each under a hairline. So the reply is the first stop the keyboard reaches
  after the conversation, and Stop, Forget, or Allow one more never stands between them. On a ticket's page it is the
  Conversation panel, beside its Work panel when wide; on an attention item its header wears the ticket's `private` or
  `public` chip and its phase, which the page says by its title and in its Work panel, and the verbs lead instead
  where they are what the item asks (The attention detail, above). When one of the ticket's attention items clears
  while its page shows it, a leaf drifts off the conversation's header, as a cleared row drops one in the list (Fun):
  the reward is for the item clearing, wherever it was answered. The attention page's answer drops none, its row
  dropping its own.
- **The reply form is always open** (`ReplyForm`), on every ticket and every chore, never folded under a `Disclosure`: a
  note for the next worker is as likely as an answer to a question, and a click to reach the box hides where the
  operator writes. Its label names the message it answers while a question waits, and on a ticket the form then
  wears the open question's tint and hairline, its label in `status-blocked`, so the question and the box answering it
  read as a pair (a task's page draws the same band around it). Its placeholder speaks of an untrusted review only
  while one waits. Focused, the box takes the accent's 8% tint, the operator's side. Its count of characters shows
  only past 80% of the bound. It is the form's rule, so the ticket's page and its attention item agree. On a
  public ticket it says what a reply is for and where it goes, `For its next worker, as an instruction. It stays in
  canopy, never on the ticket.`, as the ticket's `public` chip says on hover and to a screen reader, where its comments
  stay on the tracker.
  A ticket's page description is its state, not what public or private means: the running run, a question waiting,
  its plan's status, and when it was last active, `run:41 running · plan waiting on you · active 38m ago`
  (`ticketDescription`).
- **A conversation** is a column of messages, each a head line over a bubble. The head leads with who, in sans
  `font-medium` `foreground`, then what (kind, run, what it answers, how) and its chips in muted mono; its id and age
  are a readout at the end away from the bubble's square corner. A tracker comment's head is its author `on the
  tracker`, the comment's id and when it was written in its tip. A message that carries on the one before it (the same
  speaker, kind, run, and channel, within five minutes, answering nothing) keeps only its chips and readout, and sits
  closer under it. A bubble is as wide as its words, up to 42rem and never past 85% of the panel, so the other side
  keeps a gutter at any width:
  `surface-raised` for a worker's report or a question answered, a hairline on `surface` for a tracker comment, quoted
  since it is data from outside the loop, the `status-blocked` tint at 8% with a `status-blocked/40` hairline for the
  question still open, the one amber bubble, a dashed hairline with muted text for canopy's note on what a tick did,
  and the accent's tint at 18% for the operator's own words, which sit on the right, their head line mirrored. A
  bubble's corner nearest its side is square.
  The question still open carries a `waiting on you` chip in `status-blocked`. A forgotten ticket's conversation
  (`TicketThread`) shows what came after the latest forget. At the oldest end, each forget heads the attempt it ended:
  a muted line saying when and how, with the branch and PRs it dropped under it, and that attempt's messages folded
  under `Show N earlier messages`, a `Disclosure`, and dimmed, since the loop no longer reads them. Only the latest
  says the loop reads what came after. The panel's count is of the messages after the latest forget.
  Bodies are rich text (below), on a 24px line (`leading-6`): always text, but for their URLs. An operator
  message no `ok` tick has read carries a `waiting for the next tick` chip in `status-running`
  (`src/lib/acknowledged.ts`), and a `seen` chip with a check, in the accent, once one has, so a reply never goes
  unacknowledged; an `awaiting_reply` item it answered carries an `answered` chip, with a line saying it leaves at the
  next tick, and so does a `plan_review` item whose plan waits on the operator no more (approved, skipped, or changes
  asked); Waiting on you counts neither. While a run works the ticket, the conversation ends on it (starts on
  it, flipped newest first), on the worker's side, as a chat shows someone typing (`WorkingNow`): a pulsing `RunDot`,
  `working now` in `status-running`, its `run:N` link, its kind, its latest tool call (`RunDoing`, below), its cost
  so far, and for how long. It comes from the runs on the stream, so it rises in when the run starts, follows what it
  does, and leaves when it ends.
- **A running run's latest tool call** (`RunDoing`, `src/components/run-doing.tsx`): one line of mono data, the tool
  in `status-running`, what the call did muted (a shell call's command, else the runtime's title; cut to fit, whole on
  hover), and how long ago. A running run's row has it where an ended run's summary goes, `WorkingNow` after the
  kind, and the run's page as its `last call` field. It is agent output, rendered as text.
- **A running agent's progress** (`RunProgress`, `ProgressPanel`, `RunProgressLine`, `ProgressMeter`,
  `src/components/run-progress.tsx`, DESIGN §41): the agent's own account of where its work stands, which the operator
  reads to know what a run is up to now, so it leads wherever it shows. Whole, it is the summary in `font-medium`, a
  meter of its steps if it has any (a segment each, 2px apart, on the bare `border` track: only done fills its
  segment, in `status-done`, so the filled ones are the `N` beside it; working fills half in `status-running`,
  wiping in and striped as a barber pole whose stripes drift along it while the run runs, blocked
  or stuck half in `muted-foreground`; to do is the track) with `N of M done · stage S`, its question, then its work
  as one checklist, each entry led by a 12px mark: a `status-done` check, the pulsing running dot, an hourglass, a
  dash for skipped, an empty ring to do. The steps are the list when it has any, `now` under the working one, and what
  it wrote is done and next folds under a disclosure; without steps, done (each with its proof in muted mono), now,
  and next are the list. What it works around follows, after an hourglass. Its question is a box on
  `status-blocked/8` with a `status-blocked/40` border while it waits (muted on `surface-raised` once answered or
  ended): `asks you`, the question, and each option a full-width row that answers with its letter on a click, its
  letter in a small square, `recommended · working toward it` after the one the agent works toward. Amber means that
  question alone: a stale update is a clock and `stale` in `foreground`, a fact about the record, never a request.
  When it was last updated, in time and tool calls, is the head line, or the right of the panel's header. A run's and
  a review's page lead with it as a `Progress` panel (`Last progress` once ended), a ticket's `WorkingNow` shows it as a
  bubble on the worker's side, a running run's row as one line (a 4rem meter and `N/M` when it has steps, what it does
  now, `asks you`, when), and the rail's working row of a worker run as its meter under the phase line, when it has
  steps. Agent text, as text.
- **A URL in journal text** (`LinkedText`): an http or https URL in a message body, a summary, a rationale, or a
  detail is a link in `accent`, underlined so it reads as one inside prose, its text the URL as written; it opens in a
  new tab. A PR shown in its own place (a run's or decision's PR) is a `PullRequestLink` (below), and so is a GitHub
  PR's address in a conversation's bubble or a chore's finding, its detail or its link, as in the harness's lines
  (`InlineCode`).
- **A chore's notes** are a conversation of the operator's words alone, after the chore's findings and runs and before
  its spend, with the note form open under them (`ChoreNotes`). With no notes the panel is its header and the form,
  and the form's placeholder says what the empty list would have: its runs follow its prompt file
  alone. A note no run of the chore has started since carries `waiting for the next run` in `status-running`
  (`src/lib/chores.ts`): no tick reads a note, so the tick chip would be wrong there.
- **Decisions** are rows (`Decisions`): the subject, a ticket or chore as a link, a unit as its ticket and repository
  (on its subject's page, the tick instead, with its age), the action as a chip, a PR as a link, and the rationale
  under them as rich text, from the action's column. A `refused:` action's chip is in `status-failed` and an
  `attention:` one's in `status-blocked` (`src/lib/decisions.ts`); the rest are plain. A tick in a list is its status,
  a dot and its word in the header's tick colors (`src/lib/ticks.ts`), cut to fit, then its id as a link, a `dry run`
  chip, how many decisions, its cost, tokens, and peak context, and when it ended; its summary under, from its id.
- **A transcript** (`TranscriptPanel`) is a session's events as rows, in the order the runtime printed them, each with
  its time from the session's first event (`+12:05`; the local time on hover). The agent's text keeps its line breaks,
  its reasoning muted and italic under a `thinking` label; past four lines, its first four and rich text's
  `show N more lines` toggle (`foldText`), whole when All open is on or a search holds a line it hides. A tool call
  is a native `<details>` whose line says what it
  did and how it ended (`src/lib/transcript.ts`): a `RunDot` in `done` or `failed`, the tool's name at its own width up
  to 14rem, the first to give way, and in monospace a shell call's command (the agent's description of it on hover),
  else the runtime's title, else its input's short values as `key=value`; under that, muted, its error's first line in
  `status-failed`, or an output of one short line that is
  not JSON; then how long it took. A canopy command that printed a refusal is `failed`, with a `refused: <guard>` chip
  in `status-failed`. It opens to its input and its output (or error), JSON indented and colored as a tick's output is
  with Pretty on (below), every value as written, in monospace blocks at most 24rem tall. A model call is a muted line
  with its number, its tokens `in · out`, as By call says them, and its cost, and its reason only when it is not
  `tool-calls`, as every call but the last is; it opens the same way to its tokens by kind, each a label and a readout
  on one line, then to the input and output sections By call shows (below), built only when opened; All open leaves
  it closed. A runtime error is tinted `status-failed`. The header has the session id, then a hairline
  rule and the modes: the order, By call, and All open, a `Toggle` that opens every call turned on and closes them all
  turned off, and is on too while a search has opened what it found. Above the rows, how many tool calls, failed and
  refused ones, and model calls, and at that line's end a search field (`Find lines`, `SearchField` at its `sm` size).
  A search keeps only the rows with a line that holds it, letters in either case and every character taken literally,
  and says how many lines and rows that is in the field; its matches are marked on the accent's tint as the search
  page's are (`MarkedText`), inside a block's
  colored JSON too (`markedTokens`). A tool call whose input or output holds it opens to it, until All open is turned on
  or off; a model call is numbers alone and is never kept. Escape or the clear button empties it, and a search nothing
  matches says so in place of the rows. A By call `Toggle` in the header, as Pretty is, groups the rows by the model
  call they came from (`byCall` in `src/lib/transcript.ts`), once the counts name two model calls (one call grouped
  is the rows in order again), hiding the search, which is the rows' in order: each call a
  `Collapsible` row, its number, what it did (its first text, then its tools by name, `read ×2`), an `unfinished` chip
  when the session ended first, its reason as above, its tokens `in · out`, and its cost. It opens to an input and an
  output section, each a `panel-label` with its tokens: the first call's input is the prompt canopy kept, in a block,
  with a muted line saying what no file records; a later call's is each tool its predecessor called, a `RunDot`, the
  tool, and its summary over its output's block. The output is the call's rows as above, in a bordered list. A call's
  body is built only when opened, and All open opens the calls. A run's id in a list (`run:N`) opens its page, which is
  the run's fields over its transcript, and a chore run's id (`chore:NAME#N`) its page, whose findings sit between the
  two; a tick's page has the overseer's under its decisions. A run or chore run that ended `failed`, `crashed`, or
  `unknown` has an `ended on` field after its summary (`EndedOnField`, `endedOn` in `src/lib/transcript.ts`): the
  transcript's last runtime error, else its last failed or refused tool call, as its time, its name or tool, and its
  first line in mono `status-failed`, a button that shows its row as the context chart's entries do (below); the page
  holds the transcript's view (`useTranscriptView`) for both. A skeleton holds its place while the transcript is read
  (`min-h-40`, only then). A transcript with no events, its log gone, its runtime naming no session, or its run yet to
  print one, is its header alone, the session and then why in a few words as its readout (`log gone`, `no session`,
  `no events yet`, `no events`), the whole reason on hover.
  A transcript over 100 rows draws the first 100 (`TRANSCRIPT_BUDGET`, `src/lib/transcript.ts`), in order or By call,
  since one at the server's bounds (2,000 entries) drawn whole is 80,000 elements, and every key typed in its search
  waited on all of them; 100 keeps the page under 10,000 elements even when a search opens every call it draws. After
  them a fold, a row on `surface-raised/50` with a ghost `xs` button in a diff's fold's words (below), `Show 60 more
  rows` or `Show 100 of 1,900 more rows` (`more calls` By call), draws the next 100; it only adds. A search still
  reads every entry, drawn or not, and draws the first 100 of the rows it keeps, the fold counting the rest; a new
  search, By call turned on or off, or another session starts again at 100. The search redraws the rows in a
  transition behind the field (`inPage`, `src/lib/in-page.ts`), which the outlet does not cross-fade (Motion, above).
  All open opens the rows drawn. A row shown from the chart or `ended on` is drawn first, with every row before it.
- **A transcript's context** (`ContextChart`, `contextShape` in `src/lib/transcript.ts`) sits between the counts and
  the rows, in either view, once a model call has its tokens. Its line, in the counts' band as their second line: a
  `context` label, the peak (`peak 30.2k at call 3`), the largest single addition as a button in the accent (the tool
  and its summary, or `text` and its start) with its tokens and the call it grew, and at its end `Show chart`, a
  `Disclosure` that opens the chart under it. The chart is closed until opened, since a transcript is opened to read
  what the agent did far more often than to ask why its context grew; each kind of page (a run's, a chore run's, a
  tick's) keeps it open or closed across reloads, as Pretty is kept (`src/lib/context-chart-open.ts`), so the rows
  start under the header, the counts, and one line. Open, a bar per call, as tall as what it was sent (input, cache
  read, and cache write), 32px wide at most and the row centered, as Charts says, so a short session's bars stand
  mid-panel rather than clumped at its left, from one baseline, the peak's at 80% with its size over it: what the call
  carried from the call before in `context-carried`, what it added on top in `context-added`, 2px apart, the top
  segment's corners rounded. The first call's is the runtime's own overhead and canopy's prompt, the prompt's tokens
  its characters over four; a call the runtime counted none of has no bar. The bars are a `ToggleGroup`'s items, each
  named for its call, size, and step on hover and to a screen reader; the axis under them, in the bars' track, names
  each call, every fifth back from the last past twelve. The legend, one word each, `carried` and `added`, what the
  first call's two parts are on their hover, sits at the axis's height in a column of its own beside the track, so a
  number stays under its bar at any count. The call picked, at first the one the largest addition grew, sits raised,
  and a line under the chart, one readout with its call in `foreground`, says what grew it: the step on the call
  before, then what that call printed (its text, and its tool calls, each input and output), largest first, each its
  share of the step by its characters (`≈4.2k`, the characters on hover), at most five and then how many more. The
  first call's line splits it into the prompt and the runtime's own; a call smaller than the one before says so and
  names nothing. Each entry named is a button that shows its row, as the line's largest addition is, open or closed:
  it turns By call and the search off, opens the row if it is a tool call, scrolls it to the window's middle, focuses
  it, and sets it on the accent's tint at 14%. A session with fewer than two calls the runtime counted tokens for has
  the line alone, with no `Disclosure`: one bar says nothing the line does not, and a call that printed only an error
  has no bar to add. The one call's split into the prompt and the runtime's own is on the peak's hover. By call, each
  call's line has its step after its input, `30.2k in (+4.3k) · 1.8k out`.
- **A tick's output** (`TickOutputPanel`, `src/components/raw-output.tsx`) is the overseer's file as written, under the
  tick's transcript, and **a run's output** (`RunOutputPanel`) its log the same way, under the run's: one muted line
  naming the file (a tick's its path, with its copy button, the one place the page names it; a run's says `the run's
  log`, whose path the Run panel shows) until `Show output`, a `Disclosure` in the header, opens it. A tick that kept no
  file has no Output panel: its transcript, read from the same file, says why. Open, it is one monospace block, its
  lines wrapped anywhere (JSON events have no spaces to break at), scrolling inside the panel (`PanelScroll`) and opened
  at its end, where stderr is; the file's size is in the header, and a cut says so above the block. A line that parses
  as a JSON object or array (the runtime's events) is colored as written, never reformatted (`src/lib/json-lines.ts`,
  `JsonTokens`): keys, strings, numbers, and literals in the `syntax-*` tokens, punctuation muted; any other line stays
  plain. A transcript's block is colored the same way when the whole of it is JSON. A Pretty `Toggle` in the header (a
  mode, raised while on) lays each JSON line out over several, two spaces a level, by the space between its tokens
  alone, so every value stays as written; it reopens the block at its end. Each tick's panel keeps its own choice, off
  until turned on, across reloads (`src/lib/pretty-output.ts`), as a list keeps its order; a run's keeps it for the
  page alone.
- **Rich text** (`RichText`, `src/lib/rich-text.ts`) lays out what an agent wrote, a run's, chore run's, or tick's
  summary, a decision's rationale, and a conversation's message: line breaks kept, `-` and `1.` lists (nested by
  indent), headings as a `font-semibold` line with space above it, `#` and `##` a step over `###` (`text-base`, a
  small step, as the page's heading ladder does not apply inside a bubble), `>` quotes as their own blocks, muted on
  a stroke at their left, a
  `---` rule as a hairline, a pipe table with its head as column headers and its columns aligned by their colons,
  scrolling sideways when wide, fenced code as a `surface-raised` block that scrolls sideways, and `code`, **strong**,
  *emphasis*, and ~~struck~~ inline. Code, inline or fenced, is `text-code`: a step under its line on a sans palette,
  where the change of face sets it apart, and the line's own size on a mono one, where a smaller copy of the same face
  reads as a mistake. Inline code sits on `code-chip`, a tint of its own ink, so it stands apart on any bubble or tint
  without a tile darker than the text around it, and keeps its ends on each line it wraps to. Every code span in a
  sentence is drawn so, through `Code` (`src/components/code.tsx`): rich text's, a harness line's, the guide's, a
  plan's, a `Notice`'s, and a command or key in a page's own copy, so one span never flips look beside another. A key or
  path shown as data on its own line (a setting's name under its label, a config file's path) stays plain mono.
  It reads nothing else: other markup, a labelled link's included, stays characters. Every piece is React text, and
  every piece but code goes through `LinkedText`, so a URL outside code is a link to itself. In a list's row it
  shows the first four lines and a `show N more lines` toggle in the accent; text one line over shows whole.
  A conversation's bubbles lay out their bodies with it too, their line breaks kept, since the operator and the
  workers break lines on purpose; on a raised bubble a fenced block sits on `background`.
- **The guide** (`/guide/PAGE`, `src/lib/guide.ts`, `GuideText`) is the operator's documentation, a page each, as
  Markdown in `src/guide/` (docs/design/CONVERSATIONS.md §22), laid out as a documentation site rather than in panels.
  On the left, the pages by group (`SOURCES`), each group a heading over its pages on a hairline, the page shown in
  the accent on an accent stroke, once the pane holds it and the article's whole measure (62.5rem, a container query
  as the plan editor's, so the rail's width counts); short of that the same list folds into a `Guide pages` toggle
  above the page. In the middle, the article at `max-w-3xl`: the group as the header's trail, the title, and the lead,
  then the body in a document's type (Primitives) with soft line breaks read as spaces, each `##` a section under a
  hairline and each heading a `#` link to itself on hover, and at its foot Previous and Next, the pages either side
  in the sidebar's order. On the right, once the pane holds that too (76.5rem), `On this page`, its `##` headings. So
  the article never narrows as the window widens: a column comes in only where the article keeps its measure. The
  sidebar and contents stick as the article scrolls. `/guide` opens the first page. It reads what rich text reads,
  `##` and `###` headings as real headings, each with its anchor as its id,
  and labelled links in the accent, underlined: `[text](page)` or `(page#heading)` to the guide, `(#heading)` on this
  page, `(/runs)` to a section, and `(https://...)` to the web in a new tab. A link to anything else stays characters,
  and `guide.test.ts` fails on it. A page opens with `# Title` and then a lead of a sentence or two, says what the
  operator sees and does in the UI's own words (`waiting on you`, not `blocked`), and leaves how the code does it to
  the code and why to the design. It talks to the operator as `you`, in plain, direct sentences, as good developer
  docs do, with the odd dry aside from a staff engineer who has seen a few incidents: an aside rides on a fact, never
  stands in for one, and they stay rare enough to land. An empty fence that names one of the repository's example
  files after its language (```` ```toml examples/config.toml ````, `EMBEDS`) shows that file whole, as it is when the
  guide is built, so a page never keeps a copy of one. A code block is colored as a diff's code is (A review), in the
  language its fence names, by Shiki's name or a file's extension (```` ```toml ````, ```` ```sh ````; `fenceLanguage`):
  plain until its grammar has loaded, then the same characters colored, and plain for good in a language canopy does
  not map (```` ```text ````). A ```` ```mermaid ```` fence is drawn as its diagram, as a plan's is (D131): an image
  on a hairline, named by its `accTitle`, drawn again when the theme or a palette changes; `guide.test.ts` fails on
  one mermaid cannot read or with no `accTitle`. A diagram is for a shape the prose would take paragraphs to hold (a
  tick's cycle, the phases), beside the prose, never instead of it. A new page is a file there and a line in its group
  in `SOURCES`; the rail's foot, under the version, opens the guide, and the book atop every other page opens its page
  about that one.
- **A question before losing work** (`AlertDialog`, `src/components/ui/alert-dialog.tsx`): a page that holds the
  operator's work not yet saved or sent asks before it is left, in a dialog centred over the canvas at 70%, on
  `surface` with a hairline border: its question as the title (`Leave this page?`), what leaving loses under it, then
  an outline `Stay`, which takes the focus and which Escape gives, and `Leave` in `destructive`. A form says it holds
  words not yet sent with `usePending` (`src/hooks/use-pending.ts`); a move within the page, such as a list flipped,
  never asks. Closing the tab asks too, in the browser's own words. A question about one item, such as deleting a
  comment, asks in that item's place instead.
- **A plan in its editor** (`PlanEditor`, `src/components/plan-editor.tsx`; docs/design/PLANNING.md §25): the plan in a
  `Plan` panel, and the comments in a `Comments` panel beside it, 20rem to 24rem wide as the page has room, once
  the page gives both 60rem (a container query, so the rail's width counts), and under it, as a list, below that. Under
  the plan, the comment being written, and a thread opened by a click on its passage, float over the plan under that
  passage instead, a card 24rem wide on `surface` with a hairline border, so the page never goes down to the list and
  back; it goes when the thread closes or the comment is sent or dropped. The plan's panel stops at its text's measure,
  51rem, so on a wide page the comments stay against the text and the room left over goes after them. Beside the plan,
  the comments are its margin, as a shared document's are (`src/lib/plan-margin.ts`): their panel drops its border and
  surface, so the room above and between the cards reads as margin, not an empty box, and its header, their count,
  sticks to the top of the page as the plan's does; each open comment is a card of its own, on `surface`, at the height
  of its passage, in the plan's order, and one that would overlap the card before it moves down to
  clear it. The open one, or the comment being written, sits exactly at its passage, and the cards before it move up to
  make room. A comment being written opens in its place among them, beside its passage, so opening one never scrolls the
  page away from what it is on. Each card is placed by its top margin and stays in the column's flow, so the comments
  whose passage is gone and the resolved ones follow the last; the cards move with their passages as the plan is edited,
  and with each other as one grows. Under the plan, the comments are rows split by hairlines, as before. The plan is
  laid out as a document (`.plan-doc` in `src/index.css`), in a document's type (A document, under Primitives), a
  table in hairlines with its header row on `surface-raised` at half, a quote muted behind a hairline. What the plan
  holds as characters (HTML, an image) is muted monospace; a link is underlined in `muted-foreground` with its address
  on hover, never a link. A Mermaid code block is drawn as its diagram (`src/lib/plan-diagram.ts`), an image on
  `surface` in a hairline box, at its own size or narrower to fit, colored from the tokens and drawn again when the
  theme or palette changes, with an outlined `Source` toggle under it at the right; its code shows above it while
  toggled on, while the cursor is in it, or while a comment or a change is marked in it. An arrow key from the line
  above or below puts the cursor in it, and out of sight it is clipped, not removed, so a screen reader still reads it.
  One that cannot be drawn shows its code, and under it `Not drawn:` and why, in `muted-foreground`. The toolbar
  (`Toolbar`, below) is `icon-xs` toggles in groups split by hairlines: undo and redo, the paragraph's style, the marks
  and the blocks (each on or off, raised while on at the cursor), then `Comment`, enabled while text is selected. Each
  control's
  tooltip names it and the shortcut the editor binds to it, on this keyboard (`Bold (⌘B)`, `Bold (Ctrl+B)` elsewhere),
  and declares the same keys as `aria-keyshortcuts`. The paragraph's style is a menu, as a document's is: its button
  names the style in force (`Heading 2 ▾`), and it lists Text and Heading 1 to 4, each set as the plan sets it, with its
  keys at the right in muted monospace and a check in the accent on the one in force; a style chosen leaves the cursor
  in the plan. After the blocks, a `Table` menu inserts a table where none is (a header row and two rows of three
  columns, as a plan's Files table is), and inside one adds a row above or below or a column left or right, and deletes
  a row, a column, or the table; what the cursor's place does not allow is disabled, and an action leaves the cursor in
  the plan. An empty plan shows its prompt in `muted-foreground` where its first line starts:
  `Write the plan here, or paste its Markdown.` The plan's header says where the plan stands, at its right: its chip
  (`PlanChip`, `waiting on you` while it waits) and its age, then after a hairline its mode, as a transcript's are:
  with the plan this one replaces, `Changes since plan 1`, a `Toggle` led by the diff icon, so it reads as a control
  while off too, that marks what changed since it over the plan
  (the words added on `diff-add` at 18%, those removed struck through on `diff-del` at 14%, where they were, as `ins`
  and `del`; a block added whole, a paragraph or heading, as one: `diff-add` at 10% behind it and a 2px bar of it at
  its left, in a negative margin so its words stay put, and a table's cell added whole on the tint alone, so a new
  section or table reads as one change, not as a pill for each run its code spans and marks break it into; a section
  moved, a `moved` label in `text-2xs` `muted-foreground` with a hairline border at its heading's end; a section
  removed, one `<details>` line where it was, `Section removed: Risks`, on `diff-del` at 8% with a 2px bar of it as an
  added block has, its words struck under it when opened, so a dropped section is one change, not a wall), pressed as
  a waiting plan opens, since that is when it is read for what changed; while pressed, how many
  changes it marks (`12 changes`, a removal and what replaced it one) and ghost `icon-xs` buttons that step the cursor
  to the change before or after it, round to the other end, the plan scrolling to it. Then `Markdown`, a `Toggle` led
  by the file-code icon, swaps the document for its Markdown in a plain monospace field (`text-xs`, the plan's measure,
  as tall as the text), editable where the plan is; while pressed, the changes, the outline, and the toolbar step aside,
  and the comments are a plain list, since their passages have no place on the page. Last, a ghost `xs` `Outline ▾`
  (`src/lib/plan-outline.ts`) lists the plan's headings, a step deeper for each level under its shallowest, the
  section the page has scrolled to as it opens in the accent (`aria-current`), and puts the one chosen at the top of
  the page under the header, the cursor at its start where the plan may be edited. While the changes are marked, a
  commented passage drops its tint, so no word wears a comment's and a change's at once, but keeps a 1px underline in
  the accent, so the operator still sees where the comments are; the open one keeps its own.
  The toolbar takes the header's second line, under the label. The header is `sticky`, and what the editor scrolls
  into view (the cursor as it types, a passage a comment shows) stops 80px below it. A selection also shows a
  `Comment` bubble over it. A commented passage sits on the accent's tint at 14%; the open one, or the one being
  commented on, at 28% and underlined in the accent; the cursor in a passage, by a click or the keyboard, opens its
  thread, and so does a click anywhere on its card, or Tab into it, which leaves the plan where it is; the cursor
  leaving it, or Escape, closes it. A thread is its passage quoted (two lines, a hairline in the accent at its left, the
  whole on hover; a button that shows it in the plan), the comment and its replies as text with their ages, and its
  actions, in words, ghost `xs` buttons in muted text as a finding's `dismiss` is, never an icon alone: `resolve`
  (`reopen`) and `delete` at the right of its quote, and `reply` under the open card alone, or one whose passage is
  gone, so the rest stay short and near their passages, as a shared document's do. While the thread is open, the
  comment and each reply carry an `edit` beside their age, which turns it into the comment form in place, holding its
  words, with `Save`; the actions hide while it is open. `delete` asks first, in the actions' place, since nothing
  brings a thread back: `Delete this comment and its replies?` in muted `text-xs`, then `Keep`, which takes the focus,
  and `Delete` in `destructive`; Escape keeps it too, and the focus goes back to `delete`; the open thread sits on the
  accent's tint, as a selected row does. A thread whose passage is gone carries a `passage gone` chip (a resolved one,
  `resolved`), on a line of its own under the quote so the quote keeps its width, and stays in the list, last; two or
  more such follow a line that counts them, with `resolve all 3`, since a new plan rewrites what it
  was asked to change and the comments on it lose their passages together. Resolved threads fold under a `Disclosure`
  (`Show 2 resolved`). A comment or reply form sends on the key Settings names, as a reply does; Escape drops one that
  holds nothing new, and puts one with the operator's words aside, open with them, so one key never loses what was typed
  (`Cancel` drops it). A form takes the cursor when it opens, after any words it holds; once a comment is sent,
  resolved, deleted, put aside, or cancelled, the cursor goes back to the plan after its passage, as a shared document's
  does, rather than to the top of the page. `Comment` again, on new words, moves an empty comment to them; one half
  written stays on its passage, and the cursor goes back to it, so its words are never lost or carried to other words.
  The plan's actions are its panel's sticky foot (`PanelFooter`), which stays at the bottom of the page while the plan
  scrolls, as a document's do, so a long plan is approved or sent back from where it is read: the caller's own actions
  (a ticket's `Approve`, the foot's one primary, then `Save`, outlined, and `Skip the plan`, ghost), then a note on the
  whole plan, one line that takes the rest of the line and a line of its own, the foot's whole width, while it is
  focused or holds words, and `Ask for changes`, outlined (the request says the plan was edited, when it was). The line
  under them says how many open comments go with Ask for changes, or how far over a reply's bound the request is, then
  what the caller says of its own actions: on a ticket's plan, that approving sends none of the open comments, since the
  implement reads the plan alone, or that an approved plan's edit is approved again. What `Approve` takes is on its
  hover. `Skip the plan`, and `Approve` while the note holds words it would leave unsent, ask first in the actions'
  place, as a comment's Delete does: the question, then `Keep`, which takes the focus and Escape gives too, then the
  action. What an action did goes under that line, and stays once the plan turns read only, Skip's, so the foot stays
  for it. An approval, once the journal holds it, is a moment of its own: its words in the accent on the accent's tint
  at 14%, as decided proposals say so, with a check, rising in, and the leaf a cleared item drops (Fun), since it
  clears the plan's item, then `Back to Attention`. Once changes are asked, the line says what `Ask again` sends,
  not that the open comments are still to go. At 820px the foot is two lines at rest. The editor keeps what it
  scrolls into view 128px clear of the foot. A ticket's plan opens on its page, `/tickets/$key/plan`; `/plan-editor`
  is kept as the editor's bench, linked from nowhere: over a sample plan on mock data only, with what the planner would
  read and the plan's Markdown under it, and outside mock, an `Empty` saying a ticket's plan opens on its page. The
  editor's Playwright tests and screenshot run against it, so its behavior is tried without a ticket's state.
- **A chore** is a line in `canopy status`'s words (`choreLine`: `running for 10m`, `last ok 4h ago, due in 1h`) in
  its latest run's state color, then how often it may start and its window (`cadenceText`: `every 360 minutes`, as
  the config and the CLI say it; `windowText`), its open findings less those dismissed, then how many were dismissed
  as `canopy status` counts them (`findingsText`: `1 open finding · 2 dismissed`; its page's findings panel the
  same, `findingsReadout`: `1 · 2 dismissed`), and what its runs cost in the last
  24 hours and 30 days (`costText`, a dash when none reported a cost). Its page's description says whether it is
  healthy (`choreHealth`): that line, while a run works how the last one ended too, since the running one has said
  nothing yet, then its open findings when any (`last ok 9d ago, due now · 1 open finding`,
  `running for 10m · last ok 2h ago`). Its Schedule panel names what the config sets: `at most` always, a window or
  `when` only when set, since a default is no fact about the chore. The page puts that spend in a table under its
  runs, a row a window: runs (`runsText`: `4, 1 unpriced`), total, average, p99, and max. A chore run is a row like a
  run's, its id as `chore:deps#2` (Names, below) linking to its page, with its findings as a chip on
  an `ok` run. A finding is one row (`ChoreFindingRow`) on a chore's page and a chore run's alike; an open one says
  how long it has been open, and on the chore's page has `dismiss` after its age, or once dismissed a plain
  `dismissed` chip and `undo`: still reported, only off the attention list; its detail and link start under
  its title. Its title is never cut: it is the finding's name and up to 200 characters, so it wraps, with the head
  line on its first line's baseline. Its id leads the row in muted monospace, at most `12rem` wide; a longer one
  wraps down beside the detail rather than squeeze the title. A row's own action is a ghost `xs`
  button in monospace in its head line, as the list-order toggle is, never a full button under the row; what it did
  goes under the row, once clicked.
- **Names** (`src/lib/refs.ts`): what canopy keeps by id is named as the CLI reads a reference, `KIND:ID`, in rows,
  trails, titles, and the tab alike: `run:41`, `review:4`, `chore:deps`, and in the same grammar `tick:2`, which the CLI
  takes no reference for. A chore run has no reference of its own, so it is its chore's and its number, `chore:deps#2`,
  as GitHub writes an issue's, and a task's run the same, `task:4#5`. Each has a link component that opens its page
  (`RunLink`, `TickLink`, `ReviewLink`, `ChoreLink`, `ChoreRunLink`, `TaskLink`, `TaskRunLink`), used wherever it is
  named, a message's head and a worktree's holder included; a page's title calls the same function. A message is
  `#5`, as its conversation numbers it, and a worktree slot `#3`, as treehouse does (`messageRef`, `slotRef`). A note,
  proposal, or lesson is `memory:3` in the same grammar (`memoryRef`), so a list of them never shows a bare number
  that reads as a row's. Nothing builds a reference in place. A PR is named as GitHub writes a reference, `org/repo#123`
  (`pullRequestLabel`; any other host's URL as written without `https://`), and only through `PullRequestLink`. A link
  into a GitHub PR, such as to one of its threads, is the PR all the same: its name goes in to the PR's page and its
  icon out to the thread.
- **The label goes in, the icon goes out.** A PR or a ticket named anywhere is its name linking to its page in canopy,
  then a small icon (`LinkOut`) opening the same thing outside canopy in a new tab, named for a screen reader and on
  hover (`acme/web#88 on GitHub`, `ABC-102 in the tracker`): `PullRequestLink`, and `TicketLink` when
  `tracker.ticket_url` is set. So one click from any run, review, decision, worktree, or ticket that names a PR
  reaches the PR's page, and one more its host.
- **A link out** (a PR, a ticket in the tracker, a finding) opens in a new tab with `rel="noreferrer noopener"`, shows
  its address without `https://` (`addressOf`) when it shows one, and ends in one icon (`LinkOutIcon`): GitHub's mark
  for github.com, bundled since Lucide has no brand icons, and `ExternalLink` anywhere else. A link never wears two
  icons. A ticket's links out sit in its page's header, under the title and its line, so they are the first thing found
  (`TicketLinks`): a `LinkOutButton` per link, an `sm` outline button in the accent's monospace, its one icon first:
  GitHub's mark for github.com, else what it opens (`Ticket` for the tracker, `GitPullRequest` for a PR, `GitBranch` for
  a branch), its label the address or, for a PR, its name, and what it opens on hover. The tracker's comes first, when
  `tracker.ticket_url` is set (`useTicketUrl`), then each repository's PR, then the ticket's branch in each repository
  that has a branch link (`useBranchUrls`, design §18); an unknown ticket's page shows the tracker's alone. A kind with
  one link is its button; with more (a ticket across many repositories has a PR and a branch in each), one button says
  how many (`3 PRs`) and opens them as a menu (`DropdownMenu`), a PR by its name and a branch by its repository, so the
  links stay one line however many repositories. The Work panel keeps each repository's PR, a `PullRequestLink`, beside
  its phase; those lines scroll inside the panel past `15rem` (`PanelScroll`), so its total cost, its actions, and the
  reply stay in reach. A worktree's branch links the same way, its name in the accent with its `LinkOutIcon`, when its
  repository has a branch link.
- **Text to paste elsewhere** has a copy button after it (`Copyable`, `CopyButton`): a branch on a ticket's, run's, or
  PR's page, a run's worktrees and log path, a chore run's log path (on its page and its row), a tick's output path, a
  session id wherever one shows (a tick's page, a transcript's header, a run's row, a chore run's row), and a review's
  commit, whole though the page shows its first 7 characters. A path copies whole though the page shows it from the
  workspace root (`CopyablePath`), joined to `/meta`'s root; until that is read there is no button, so a copy is never
  the short path. The button is a ghost `icon-xs` with the `Copy` icon, muted until hovered; a click shows `Check` in
  the accent, or `X` in `status-failed` when the browser refuses, for 1.5 seconds, and names what happened
  (`Copied branch`), and a toast says the same with the text it copied, on one line. In a dense list (a worktree slot's
  path and branch, a run's or chore run's session id, a chore run's log) it shows only while its row (`group/copy`) is
  hovered or it has the focus, keeping its space so nothing moves, and always on a touch screen. The clipboard needs a
  secure context (https or localhost), so elsewhere there is no button and the text stays selectable.
- **A toast** (`Toaster`, `useToast` in `src/hooks/use-toast.ts`) says what an action did when the place it was done
  shows too little of it: a copy names what it copied, a draft's send what it sent. It sits at the bottom center of the
  window on `surface` with a hairline, a `Check` in the accent or an `X` in `status-failed`, its title in `text-sm`, and
  a line under it in muted monospace `text-xs`, on one line with an ellipsis where it is cut: a copy's text is on the
  clipboard, whole, and a send's URL under its card. It closes on its own after 3 seconds, held while the pointer or the
  focus is on it, or when swiped down; F8 reaches it from the keyboard and Escape closes it. At most three show, the
  newest last. A screen reader announces it. It never carries an action, and it is never the only place an outcome
  shows: the control that acted says so too, and a refusal is still a `Notice`. A reply that moves the attention page on
  (The attention list is an inbox, above) takes its form with it, so its toast says what it did, and its item's row and
  conversation keep it. `main.tsx` renders the one `Toaster`, around the router, so a toast outlives the page it came
  from.
- **The note of what changed while away** is the one toast no action shows (`useAwayNote`, `src/lib/away.ts`).
  Shown again after it was hidden 10 minutes or more, the tab says in one line what changed meanwhile: what newly
  blocks work first (`blocking`, as the tab's count), then the items cleared, the PRs opened, and the runs ended
  (`Since 14:05: 1 new item needs you, 3 items cleared, 2 PRs opened`), each count of none left out, and nothing at
  all when every count is none. A `History` in the accent, no line under it, and 8 seconds before it closes, since it
  is read on coming back rather than seen as a click lands. Every count is read after the return, never told from
  what the tab held: the attention list as the stream sends it again, against the one the tab held as it was hidden,
  and the runs counted over the whole journal (`GET /api/runs/since`), not the runs list's recent few. With no fresh
  list within 30 seconds, as while the loop is down, it says nothing. A tab never hidden, as on a second monitor,
  never shows it.
- **Every field the operator writes in to send** (a reply or note, a plan comment, a review request's notes, a draft
  or a lesson in their own words, the notice to workers) sends on the key Settings names, through `useSendKeys`: Enter
  by default, as a chat does; Ctrl+Enter (⌘+Enter on a Mac), Enter making a new line; or Button only. Shift+Enter
  always starts a new line, and an Enter that ends an IME composition only commits it (`src/lib/send-key.ts`). The key
  submits the form, so the form's submit checks what its disabled button does. A reply's field is named for the form,
  as its panel is for its page: `Reply`, `Note`, or `Reply to message 5` while a question waits. The send button names
  its key in a keycap (`SendKeycap`) after its label, tinted with the button's own color: ⏎, or ⌘⏎ on an Apple
  keyboard and Ctrl⏎ elsewhere; Button only shows none. The keycap is `aria-hidden`; the button carries the same keys
  as `aria-keyshortcuts`.
- **Behavior comes from Radix**, through the shadcn wrappers in `src/components/ui/`, and only they import it (the lint
  refuses `radix-ui` anywhere else): a button that is on or off is a `Toggle`, a part of the page that opens under its
  button is a `Collapsible` (the panel or row itself, by `asChild`, so it adds no wrapper) opened by a `Disclosure`
  (below), an option that is on or off a `Checkbox` (or, for the lightswitch rave alone, a `Switch`), a choice of a
  few options a `ToggleGroup`, and a row of an editor's controls a `Toolbar` (`src/components/ui/toolbar.tsx`), one
  tab stop with the arrow keys between them.
  Radix keeps their ARIA in step with their state (`aria-pressed`, `aria-expanded` with `aria-controls`), so a
  component never writes it by hand. Two stay native on purpose: a transcript's tool call is a `<details>` (above),
  and rich text's `show N more lines` (`MoreLines`, a transcript's thinking's too) shows more of text already on
  screen rather than opening a part, so it is a plain button with `aria-expanded`.
  A new wrapper is shadcn's, added or ported as `button.tsx` was.
- **Modes and disclosures** follow one rule each, so a control says which it is before it is clicked:
  - A **mode**, a way of showing what is already there, is a pressed `Toggle`, a ghost `xs` button raised while on,
    labelled with the mode and never with what a click does: Pretty, By call, a transcript's All open. It names the
    mode in both states; `aria-pressed` says which. A list's order, which has two values and no off, is the one
    exception (`OrderToggle`): it names the order in force (`newest first`), the arrow saying it flips.
  - A **disclosure**, what opens a part of the page under it, is a `Disclosure` (`src/components/disclosure.tsx`) on
    its `Collapsible`: a ghost `xs` button, a chevron that turns down while open, and what it does in words,
    `Show <what>` closed and `Hide <what>` open (`Show output`, `Show chart`, `Show 2 earlier runs`,
    `Show 37 slots, #4 to #40`, `Show hats`). In a row's line it sits in line with the text above it (`-ml-2`), no
    taller than a line (`-my-1`).
    A row that opens to its own body, a transcript's tool call or model call, is the row itself, a chevron at its end.
  - Two of either are one: a pair that does and undoes (Open all, Close all) is one `Toggle` (All open).
  - A panel header's modes sit together, after what the panel is about: a transcript's session id, a hairline rule,
    then its order, By call, and All open.
  - A panel kept at hand but seldom read whole arrives folded (`FoldPanel`, `src/components/fold-panel.tsx`): its
    header, a readout that says what it holds in a few words, and a `Disclosure` that opens its rows under it, built
    only once opened. A run's Memory is one, a review draft's `What the reviewer found`, and the Prompt on a run's, a
    tick's, and a chore run's pages (`PromptPanel`), its length and a copy button as its readout, `none kept` alone
    when canopy kept none.
- **Buttons come in three sizes**, each one look: the default (`h-9`, `text-sm` at 500) in a form and a panel's foot;
  `sm` (`h-8`, the same type) in the header and for a link out, whose label is the accent's monospace at that size and
  weight (`LinkOutButton`); and `xs` (`h-6`, `text-xs` monospace at 400, as a readout beside it is) in a panel's header
  and a row, a `Toggle` or a `Disclosure` included. A button never sets its own size or weight.
- **Options that are each on or off** (the ticker's topics) are a row of checkboxes (`Checkbox`,
  `src/components/ui/checkbox.tsx`), each inside its label, so a click on the word toggles it too: a box on the raised
  surface, filled with the accent and its foreground's tick when on. The row is a `fieldset` named by the line beside
  it.
- **A choice of a few fixed options** (a theme, the ticker's speed, the send key) is a segmented control
  (`ToggleGroup`, `src/components/ui/toggle-group.tsx`): the options in a well on the canvas, the picked one raised on
  `surface-raised` with `shadow-xs`. It is a radio group, so one option is always picked: the arrow keys move between
  them, Space picks one, and Tab leaves the group.
- **A choice of repositories** is a repository picker (`src/components/repo-picker.tsx`), never a chip or a segment for
  each, since a workspace may have dozens: an outline `sm` button in monospace `text-xs` saying what is chosen
  (`every repository`, in `muted-foreground` while it narrows nothing; a name; two; then `3 repositories`), opening a
  list on `surface` under a field that keeps the names holding what is typed (cmdk, through
  `src/components/ui/command.tsx` alone). A filter (`RepoFilter`) takes several: a check in the accent marks each one
  chosen, picking one keeps the list open, `every repository` heads it and clears them, and what was chosen as it
  opened is listed first, so nothing moves under the pointer. It is kept in `?repo=` as names joined by commas
  (`src/lib/repo-filter.ts`), replacing the history entry as a filter field does, and a row shows when it is in any of
  them. In a form (`RepoSelect`) it takes one, and picking it closes the list. The runs page's filter by model
  (`ModelFilter`, `?model=`) is the same picker of one, `every model` heading it, each id whole, as a gateway can list
  dozens; the button, list, and item are `src/components/picker.tsx`, which both build on.
- **A config page** (`ConfigForm`, `/settings/limits`, which Settings links to from a one-line panel so Settings stays
  short): the keys in panels by what they govern (`CONFIG_GROUPS` in `src/lib/config-settings.ts`), two to a row on a
  wide window and Trust across the whole row, a key no panel names in an `Other` panel. A row is the key in words over
  its name in the file in monospace, where its value comes from, and how far the page may take it, and its control at
  the row's end: a numeric field in `readout` type, a checkbox for a switch, and a list's entries as checkboxes to
  clear. A switch already on its stricter side is disabled, not hidden, so the page still says what it is.
  `capacity.repo_slots` lists only the repositories with a count of their own, a field each, and under them a repository
  picker (`RepoSelect`) to give another one a count, so a workspace of many repositories does not get a field per
  repository. One save bar, sticky at the page's foot so a change far down the page is never left unseen, says how many
  changes wait, with Discard and Save, each disabled until something changed; a field that is not a whole number is
  named in its `Notice` and keeps Save disabled. A save reads the file again, and the `Notice` keeps what the save did
  over the fresh form.
- **An action** is a button in the foot of its subject's identity panel (the detail skeleton, above), under a
  ticket's reply (The answer, above), or under its form, with one line under it (`Notice`): what the action did, in
  the CLI's words, or its refusal in
  `status-failed`, naming the guard. An action that kills something asks
  once more inline (Stop now, then End run N now), never through a browser dialog. One that cannot be undone asks
  for its subject typed out: Forget opens a form in `status-failed` that says what it drops and keeps, and its button
  stays disabled until the field holds the ticket's key exactly. Until then Forget is the quietest of the row, a ghost
  button in `status-failed` text at its end, since the loudest button is the one clicked first. The line under the
  actions is absent until one has said something: what the ticket is, private or public, is its chip. No empty line
  is held for it, since a blank band at a panel's foot reads as a layout fault; it appears under the button that was
  just clicked, so what moves is below the operator's eye. A failure that is not a refusal says what happened in
  canopy's words, never the browser's (`failedText` in `src/lib/outcomes.ts`): no answer at all is
  `canopy did not answer: is canopy loop running?`, and a status with no words of its own says whether the action was
  done, `nothing was done` for a 4xx and `it may not have been done` for a 5xx, which may come after the write. The
  header's Pause and Tick now say the same on hover. A public ticket
  has no Stop, since its queue label authorizes it; while a worker runs on one, a muted line stands in Stop's place:
  `Public: remove its queue label to stop it, or start it privately.`
- **A choice of persona** is a menu (`DropdownMenu`) on an outline `xs` button naming the choice
  (`src/components/personas-menu.tsx`): a ticket's agent's picks one (`PersonaRadioItem`), a review request's checks
  several (`PersonasMenu`). Each item is the persona's name in monospace over its description, its file's own or
  else its opening sentence, in muted `text-xs`: the name is the item's accessible name, the description its accessible
  description.
  A persona canopy would refuse is disabled, with why on hover. The menu ends, after a hairline, with what goes back
  to the config: `Clear the override`, or `Use the default`.
- **A choice of model** (`ModelPicker`, `src/components/model-picker.tsx`) is the same menu over the models the
  runtime lists, read as a row naming a model shows, so one gone is marked before the menu opens, else when it opens:
  the button, then where it comes from in muted `text-xs`. A ticket's agents (`src/components/ticket-models.tsx`) and
  a review request (`ReviewModelMenu`, `src/components/review-model.tsx`) build on the one picker. A review request's
  is `Model` beside its personas, its button reading `default` in muted sans while none is picked and config's
  reviewer's model named after it in muted `text-xs`, so it reads the list as it shows only once a model is picked;
  its ghost button under the list is `Use the default`, and the pick is that request's alone. On a ticket's page it
  shares one grid with
  the persona (`src/components/ticket-agents.tsx`): a row per agent, its name, its persona, then its model, under a
  muted `persona` and `model` heading, so the conversation under the panel stays in reach; a Work panel narrower than
  `@lg` puts each model under its persona. The persona's column is as wide as its widest, up to 45%, and the model
  takes the rest. A model's id is monospace, and a long one ends in an ellipsis, on the button and in the list, whole
  on hover; the runtime's default names none, so its button reads `runtime default` in muted sans, and a muted
  `last served` names the model that served the agent's latest read run when it is not the button's. A variant on the
  button follows the model's id, muted. Each model's variants are items of their own under it, indented, in the
  runtime's order, each `@variant` to the eye and named whole for a screen reader; a model with variants is marked a
  muted `(default)`. The field finds each item by its own id alone, and sets the pinned item aside while it holds
  anything, so Enter takes the first id found; a variant whose model is hidden shows its model's id before it, muted.
  `Clear the override` is a ghost button under the list, out of its scroll. A choice saved is confirmed in its row, a
  `saved`, or `cleared` for a clear, in `status-done` in place of where the model comes from, so nothing below moves,
  until the ticket's models change after it; one that sets aside config's variant says so after it in muted text. The
  menu offers only what the server would take: the model chosen now, when it is not one, is a disabled item with why
  under it, out of its disabled look, in `status-failed` `text-xs` (`no longer listed; its next run is refused`,
  `variant no longer listed; its next run is refused`), and a model or variant gone from the list marks its trigger in
  `status-failed`, as its attention item's chip is. A list that cannot be read says why in `status-failed`, in a
  read's words (`whyReadFailed`), offers no model, and has a `Read again` item. While a choice saves, its trigger
  names it with a trailing `…` and is `aria-busy` and `aria-disabled`, never `disabled`, so the focus the list hands
  back stays on it; a refusal's `Notice` is in its agent's row.
- **Attachments** (`src/components/attachments.tsx`, DESIGN §22) are a section with a `panel-label` heading, under the
  verbs at the foot of a ticket's or a task's conversation, beside the reply that says what to do with them: each file a
  row of its name in monospace, its size muted, and a ghost `icon-xs` ✕ named `Remove NAME`; an outline `xs` **Attach a
  file** beside the heading opens the browser's file picker, from a visually hidden input. A muted line says how much of
  the limits it holds. The page refuses a file over the bound or not UTF-8 before sending it, as an `ApiError` naming
  the CLI's guard, so it reads in the `Notice` as the server's refusal would.
- **A limit something is stuck at** (`GrantLimits`) sits under a ticket's actions, after its reply on its page and
  on its attention item (The answer, above), but under the run on a broken run's item, which asks for another try
  first, and in the foot of a PR's Pull request panel, under the operator's review request. While something is stuck
  it is a block on the
  `status-failed` tint, the color its `attempt_limit` chip wears, so it stands out from the panel: a line in body text
  led by `At its limit.` in `status-failed`, then a row per limit whose runs have reached it, what it counts in
  monospace (`resume in web`, `reviews of web#88`, just `reviews` on the PR's own page), its runs against it in
  `status-failed` (`1 of 1 runs`, and `, N granted` past the policy's), and an outline `Allow one more` button at the
  row's end, the default size of every button in a panel's foot, as a ticket's actions are. Under the row, in muted
  monospace `text-xs`, is the CLI's command for the same grant with a `Copyable`: in the text, not a tip, since it is
  something to type. What the grant did goes under the rows (`Notice`), untinted once nothing is stuck; the row
  leaves once the limit is above its runs. A limit with room left shows nothing.
- **A review request** (`ReviewRequestForm`, `ReviewRequestStatus`) is how the operator has canopy review a PR the loop
  does not own (DESIGN §21). The reviews page leads with a `Review a PR` panel above the list, whose form is one
  column capped at `max-w-3xl`, every part on its left edge and to its width: the PR's URL in a monospace field, and
  under it a line it always holds, so nothing below moves as it changes: the PR's reference once canopy would take
  the URL (`acme/web#88`, as the reviews list writes it), that it is not a PR's URL, which canopy would refuse, before
  it is sent, or, empty, that a link into the PR will do. Then the notes, always open since the operator often has
  some, under a sentence-case field label (`text-xs font-medium`, `(optional)` muted), never a `panel-label`. Then who
  reviews it, one row with nothing folded: `Persona` and its menu, muted text after it saying `as Settings prefers`
  when the choice is Settings', its trigger naming the config's `(default)`, then `Model` and its menu (A choice of
  model), each label the same field label, and at the row's end `Review`, the form's primary (the default button),
  with its keycap and the CLI's command on hover, its right edge on the fields'. The row wraps in a narrow box. The
  dialog's form ends on one quiet line (`Notice`) saying its review is a draft that posts nothing until published,
  which a refusal replaces; the reviews page's has only the refusal, since its description says the rest. On
  success the form opens the PR's page. It takes no repository: the overseer finds the PR's (DESIGN §21). A PR with
  an open request wears a `requested` chip after its review in the list. On a PR's page the request is a line in the
  foot of its Pull request panel, since when, with an outline `Stop` at its end while it is open, or how it ended
  once it has. While none is open on a PR the loop does not own (`loop_pr` false), the line's end holds the personas
  menu, the model menu, and an outline `Review this PR`, `Review again` once the PR has a review or an ended request;
  the loop's own PR without a request has no line. A request's personas and its model, open or ended, are a line
  under it. What either button did goes under it (`Notice`). Until its review starts, the reviews list has a
  `requested` row for it, whose ticket's place names the PR's author in muted monospace once canopy has read the PR,
  since it has no ticket.
- **A review** (`/pull-requests/reviews/$id`) is canopy's shadow PR review, kept in the journal (D114); on a PR the loop
  does not own it is also a draft the operator may publish, word for word, as their own (A review's draft). The page
  holds the review's fields, its findings as a list linking to each one's card, and the diff, a panel per file. Its
  header has the PR's link out, as the PR's page does (`PullRequestLinksOut`), with or without a draft. Each fact is
  said once. The description is the run's status alone (`done`), and the Review panel's header has no dot. The panel
  leads with the reviewer's summary, the answer the operator came for, then the `harness` line when the harness decided
  the status, then the verdict, in its worst finding's color with its impact chip (its one home, since the description
  is plain words and could carry neither), the PR, with the PR's other reviews on a muted line under it (`also review:1,
  1 blocking finding`, each verdict in its color), the ticket, the commit, when it ended, and what it spent. A diff is a
  monospace table: the old and new line numbers, the `+` or `-` in `diff-add` or `diff-del`, and the line, its row on
  that token's 12% tint; a hunk's header on `surface-raised`; long lines scroll sideways inside the panel, while a
  finding's card and a fold keep to the panel's width at its left edge (sticky, `100cqw`), so one long line never
  carries a card's text out of reach. The code is colored by the file's language, read from its name
  (`src/lib/languages.ts`): keywords in `syntax-literal`, strings in `syntax-string`, constants in `syntax-number`,
  function and type names in `syntax-key`, comments muted, the rest plain, each read at 4.5:1 on an added or removed
  line's tint too. Shiki tokenizes each hunk's new side and old side whole, with its TextMate grammar, in the browser
  (`src/lib/highlight.ts`, D121), 200 lines at a time from the grammar state the last left, the page running between
  them, so a long diff never holds a click; a line shows plain until its file's grammar has loaded, then the same
  characters colored, and stays plain for a language canopy does not map, a file of more than 2,000 lines (more than the
  page draws of a diff at first, below, so mostly folded away; `highlightLanguage`), a line of 1000 characters or more,
  or a grammar that fails. A diff over 2,000 lines folds (`DIFF_BUDGET`, `src/lib/review-folds.ts`), since one at the
  server's bounds drawn whole is 150,000 elements, seconds to show and seconds for every click after: the page draws the
  10 lines either side of each finding's line, then whole files in order while they fit, then the first lines of the
  rest, and says so in a muted line above the first file. Each run of lines it leaves out is a fold, a row on
  `surface-raised/50` with a ghost `xs` button, `Show 60 hidden lines`, or `Show 500 of 13,029 hidden lines` past a
  step, which draws the next 500; a fold only adds, as rich text's `show N more lines` does, so it is a plain button,
  not a `Disclosure`. A transcript's rows fold the same way past 100, a step of 100 (`TRANSCRIPT_BUDGET`, A
  transcript, above): its row is some thirty elements to a diff line's few. The panels take any card anchored at a
  line (`DiffPanels`, a card renderer and a `place`d list), so a PR's threads sit on a run's diff as findings do on a
  review's (A PR's threads, below). A file's panel folds away whole on `Hide diff`, a `Disclosure` at its header's
  end, to its header and a muted line counting what it hides
  (`9 lines and 1 finding folded away`). Above the first file, an outline `xs` button names the file types shown
  (`All file types`, `.ts only`, `2 of 3 file types`) and opens a `DropdownMenu` of them, each a checkbox item with its
  count of files, every one ticked at first; unticking one hides its files, the menu staying open so several flip in
  one go, and a muted line beside the button counts the files hidden, with `Show every type` under them to tick them
  all again. A file the filter hides keeps its fold and the lines opened in it. A link from a review's findings list to
  a card ticks its file's type and opens its panel, each time it is followed, so a link never lands on nothing. A
  finding's
  card (`FindingCard`) sits right under the line it names, or under its file's header when the diff does not show the
  line, or in a Not in the diff panel after the files. A review with no diff kept shows each finding once: its
  findings list is their cards, a checkbox leading each that can be sent, and the Diff panel only says no diff was
  kept. A card holds its number, its severity as a chip (`blocking` in `status-failed`, `major` in
  `status-blocked`, as the attention list's reasons; `minor` plain), its title, its location, and its detail as rich
  text, with `dismiss` at the end of its head line (`useDismissReviewFinding`); a dismissed one has a `dismissed` chip,
  its title muted, `undo` in place of `dismiss` (as on a chore's finding, and as `canopy dismiss --undo`), and the
  same chip in the findings list. On a review of one of the loop's own PRs (`sendable`), each finding in that list
  the operator has not dismissed has a checkbox before its number, and under the list `send to a worker` sends the
  ticked ones together, as `canopy send review:ID N...` does, with a muted line saying what it does until it has said
  what it did. The list of reviews is a `ReviewsTable`: its run state's dot and its verdict in its
  worst finding's color (`verdictTone`: a blocking one's `status-failed`, a major one's
  `status-blocked`, else plain), so a review with a blocking finding never reads as calm as a clean one, and the worst
  in words, since color alone says nothing to some (`verdictText`: `3 findings, 1 major`, or `1 blocking finding` when
  every finding is that bad); the review's link; its ticket
  (or `None`, its reason on hover), its impact, then in the free column the PR (`PullRequestLink`), its title
  (`TicketTitle`: the PR's own, else as canopy's reader last read it, else its ticket's, and nothing without one) in
  what room the rest leaves, left out below `@6xl`, where that room is a word at best, and the commit's first 7
  characters, then cost and age. A review's page colors its verdict the same way.
- **A review's draft** (`ReviewDraftPanel`, DESIGN §34), on a review of a PR the loop does not own, leads its page,
  which is the draft's one record: the title is `review:5 Your review of acme/api#14 by carol` (the PR alone while
  canopy has not read its author), and the description the draft's state (`ReviewDraftState`), its status chip
  (`REVIEW_DRAFT_TONE`: staged and unconfirmed in `status-blocked`, publishing as running, the rest plain, since nothing
  waits on a draft), its version, and what the status means. The `Draft review` panel comes first; canopy's Review
  fields and Findings fold under it into one `FoldPanel`, `What the reviewer found`, its readout the run's status and
  verdict, its findings an `h3` under the fields; the diff follows. A review with no draft keeps the page above. The
  panel's header names the version in a muted readout, what made it and its hash in its `Tip`; then a muted line saying
  it is what would post, word for word, on which commit, and to read it first; a `status-blocked` line when the PR's
  head has moved past that commit; the body as `MemoryText` with a ghost `xs` `edit`; its comments as rows linking to
  their cards (a `draft-comment` row: its number, `finding N` or `yours`, its first line, its line), and a muted line
  under them naming the findings it leaves out; every version in muted monospace, the newest in the foreground; and in
  its foot the one way canopy posts as the operator, as a PR's thread drafts are sent (A PR's threads, below): a default
  `Publish version N`, which submits it, and beside it an outline `Start the review on GitHub`, which stages it, each
  with its command on hover, and a muted line by them saying what posts: as you, on the PR's author's PR (`the PR` when
  canopy has not read it), the body and how many comments, on which commit. A publish says what it did in a toast;
  staged or published, the foot says so in one line linked to GitHub instead, never a raw URL. A ghost `Discard` after
  them asks in its place, as skipping a plan does (Keep focused, Escape keeps), and a discarded draft's foot says so in
  one line. On the diff, one card per point of the review: each finding's card is its comment's too (`ReviewPointCard`,
  a draft's card, above, never a `FindingCard` beside a comment's card). It heads with the finding's number, severity,
  title, and location, then a chip, `in your review` or `left out`; in the review as a comment, its text is that comment
  as it will post, with `Edit` while the draft waits; through the body, or left out, the reviewer's detail, and a muted
  line saying where it posts or how to have it back. One ghost `xs` control ends its head line where a finding's
  `dismiss` is: `leave out` dismisses it, `put back` takes that back (`useDismissReviewFinding` with the draft's words),
  so the two are one choice, as DESIGN §34 ties them. A finding left out by a drop or a body edit rather than a
  dismissal shows `dismiss`, since the server puts a finding back only by taking its dismissal back. Once the draft is
  published or on its way, the control is the plain `dismiss` or `undo`. A comment the operator added keeps a card of
  its own (`DraftCommentCard`) under its line after the findings there, with `Edit` and `Drop` while the draft waits;
  with no diff kept, every comment's card is in the panel's list, as before. While it waits, each line of the new side
  has a ghost `+` beside its number (`DiffPanels`' `onAdd`), shown on the row's hover or its focus, which opens a new
  comment's card under the line, its form open.
  A review whose request made others of the same commit in other personas names them in a muted line under the intro,
  `Also reviewed as skeptic, eddie`, each persona a `ReviewLink` to its page, and that each is a draft of its own:
  the operator picks one to publish, and publishing it changes none of the others.
  Outside its review's page a draft is its status alone (`ReviewDraftChip`): `draft` while it waits, else the
  journal's word, in `REVIEW_DRAFT_TONE`, with the word and what it means on hover. A review's row and a PR's carry it
  after the verdict (a PR's, its newest review's draft that has one), where its state is, so the list's left edge says
  which of the operator's reviews wait on them; the verdict is cut first. A PR's Pull request panel carries it as
  `your review`, with the review's `review:N`.
- **A PR** (`/pull-requests`, `/pull-requests/pr?url=`) has a section of its own. A PR's row: where it stands, which is
  the run working it now while one does (a pulsing dot and `run:N`), then its latest review (its state's dot unless a
  run's leads, `review:N`, and its verdict, in its worst finding's color; `not reviewed` muted), its draft's chip, and
  `requested` while the operator's request is open; the PR (`PullRequestLink`, the URL on hover); its unit's phase as a
  chip; then its ticket and title (or `none: canopy only reviews it`, `None`) in the free column, and its age. The
  ticket shares the free column with its title: a column of its own, beside where the PR stands, would not fit a 1280px
  window. Its page: the PR's name (`org/repo#123`) as the title, then its own title as its worker reported it, else its
  ticket's, with its phase as a chip. Its description is where it stands, as its row leads with it: its latest review
  and that review's verdict (`review:4 3 findings, 1 major`, or `not reviewed`), `at its review limit` while it is, the
  run working it now, and for a PR canopy only reviews, `canopy only reviews it`, said there alone; its ticket and how
  many reviews it has are said in its panels, not again there. A link out follows, as a ticket's page has
  (`LinkOutButton`), saying where it goes (`on GitHub`) rather than repeating the title. Then panels: its fields (its
  ticket, a `TicketField` left out when it has none; its branch; its total cost; no repository, which its name says),
  with a grant of another review in its foot when it is at its review limit; its review threads when canopy has read
  them or holds a draft for it (below), led by its feedback plan while that waits on the operator; then its reviews
  (`ReviewsTable`), the runs that pushed to it (`RunsTable`), and its decisions, each a `ListPanel`, so an empty one is
  its header alone, and no Runs at all on a PR with no ticket, since runs are a ticket's.
- **A PR's threads** (`ReviewThreads`, DESIGN §29) are its coworkers' review threads, as canopy's reader last read
  them, on the diff the latest run kept, with the replies runs drafted under them. The PR's detail says up front
  whether there are any (`threads`), so their place is held (`PanelLoading`) before they arrive. A `Review threads`
  panel leads: what `trust.review_replies` means for them in a line, when the PR was read and at which head, a
  `head-moved` line in `status-blocked` when the PR's head is past the kept diff's commit, a `Drafts` list of every
  draft in the order their cards show (a `thread-draft` row: its status chip, `run:N` and its number, its first line
  linking to its card, or its reaction's name for one it sends alone, and where the card sits in muted monospace),
  whose links open the card's file as a review's findings list does, the drafts for the review's body, and in its foot
  `Send N waiting`, which sends every waiting draft as one comment review, its command on hover, and an outline `Start a
  review on GitHub` beside it, which stages them in a pending review instead, its reactions added at once, with a muted
  line saying what each does; while the PR holds a staged review, neither shows, and a `staged-review` line links to the
  PR's files on GitHub to finish it. While its ticket has a current feedback plan (docs/design §32), a `Feedback plan`
  panel (`FeedbackPlanPanel`) comes before the `Review threads` panel while the plan waits on the operator, stale or
  not, so its Approve is in a 1720×1440 window's first screen, and after it once approved or spent; where it sits is
  settled as each plan is first read, so one approved meanwhile stays put, its band in view. The panel:
  `feedback-plan:N` and its status as a chip in its header (`waiting on you` and stale in `status-blocked`, approved as
  running, spent plain), a muted line of who planned it and what its status means, cut to the status once it is
  approved, a
  stale plan's changes in `status-blocked`, a row per item (a `Checkbox` until a resume spends it, its number, the
  first line of what was said as `MemoryText`, and where it is: `on its thread`, a router `Link` to the thread's card
  by its `threadAnchor`, `the review`, a link out to it on its host, or the other PR it is on; under that, muted, its
  proposal as a chip in its tone, its author, `trusted`, `for the next plan` on one an approval did not tick, the
  plan's first line on it as `MemoryText`, and its id; and a reply no
  thread card shows, under `Proposed reply`, as `MemoryText`), and
  in its foot the operator's words and `Approve whole` or `Approve N of M`, its command on hover (`Approve stale
  plan` then `Approve as it is` for a stale plan's two steps, the first refusal a muted `output` rather than a
  `Notice`; disabled with no box ticked or no file; an outline `Approve again` once approved, at rest until a box or
  the words change), an approval done as the `ApprovedBand` a ticket's plan gets, then a `Disclosure` of the plan's
  file as `MemoryText`, or a muted line naming the file's problem. Then the diff (`DiffPanels`), each thread's card
  (`ThreadCard`, `surface-raised`) under its line, under its file's header when outdated or off the diff, and a
  `Not in the diff` panel for the rest (`Threads` when no run kept a diff), and `Not on a thread` for drafts no read has
  placed. A thread's card: where it is in muted monospace, `outdated` and `resolved` chips, each comment's author, a
  `bot` chip, `sent by you` on one the operator sent, its age, a `LinkOut` to it, and its body as `MemoryText`, plain,
  its line breaks and tabs kept and every other hidden character named, never Markdown or a link; a draft's text the
  same. A thread the feedback plan covers carries its proposal above its drafts (`PlanProposal`, an inset rule, a
  hairline `border-l-2` on the thread's card, not a card of its own): `Plan item N`, the proposal as a chip in its
  tone, `for the next plan` once an approval did not tick it, and the reply as `MemoryText`; a `change` its resume is
  still to act on, over a waiting draft, says in `status-blocked` that the resume writes a new reply there and sending
  the draft first answers ahead of it, the draft's `Send` left as it is. An item an approval did not tick is `for the
  next plan` wherever the page says so (its chip, the hint beside the button), and its box is named `approve item N`,
  never `left out` or `leave`: `leave` is a proposal, to leave the item be, which ticking it approves; the CLI's flag
  stays `--leave`, on the button's hover.
  Each proposal's chip has a quiet tone of its own (`proposal-*`), so `change`, the one that edits code, stands out,
  `decline` and `ask` sit apart from it and from each other, and `leave`, which does nothing, stays plain.
  A comment's `<details>` blocks are the one thing read in it (`CommentText`, `src/lib/details.ts`): each folds,
  as on GitHub, in a hairline box under a `Collapsible` row of a chevron and its summary in `font-medium`, open when
  written `<details open>`, and a closed one that folds a hidden character carries `hides a character` in
  `status-failed`. Only bare `<details>`, `<details open>`, and `<summary>` are read, so a dropped tag hides nothing.
  A draft's card (`DraftCard`, a draft's card, above) heads with `Draft`, `run:N` and
  its number, its status as a chip (`DRAFT_TONE`: waiting, unconfirmed, and staged in `status-blocked`, refused in
  `status-failed`, sending as running, the rest plain), the run's stance as a muted word, `your text` once edited, and
  its hash at the end in muted monospace, the one a send carries; then the harness's reason for a status other than
  waiting, a `status-blocked` warning when it replaced a draft the operator edited, and its text as `MemoryText`, struck
  and muted once superseded or dropped,
  left out when the draft sends its reaction alone. A thread's draft that stages a reaction says so in a muted line
  under the text (`draft-reaction`): the emoji, hidden from screen readers, then its name and whether it goes with the
  reply or alone; one a failed send already added says so in `status-blocked` (`draft-reacted`). Its
  verbs: `Send` (default) on a waiting draft, `Edit` and `Drop` on one waiting or unchecked, ghost `Undo` on a dropped
  one, and a `LinkOut` to a sent one. `Edit`'s form holds, on a thread's draft, a `Reaction`
  `ToggleGroup` of GitHub's eight in its picker's order, each an emoji named for screen readers, the lit one pressed
  again for none; `Save` also takes an empty text beside a reaction. What each verb did goes under it
  (`Notice`), in `canopy draft`'s words. `Send` reads `Sending…` until the post returns, and a toast says what the send
  did as well, since a send speaks for the operator outside canopy and the line under the card leaves with its attention
  item at the next tick: the draft's fate, or how many of several reached the PR, with the URL when they share one, and
  a cross when any is not on the PR. A ticket's own drafts (`TicketDrafts`) are a `Drafts for the ticket` panel
  under the ticket page's grid, shown only when it has any, each card naming the issue it goes to in monospace, as
  text and never a link, since a worker named it.
- **Search** sits atop the nav on every page (`SearchBox`, a `SearchField`): a magnifier, the field, and `/` in a
  keycap, its shortcut from anywhere but a text field. While the field holds text, a ghost clear button (`X`, on the
  keycap's `bg-muted` when hovered) takes the keycap's place: it empties the field and keeps the focus there. An empty
  field, by the button or by deleting its text, empties the search page if it is open, and leaves any other page as it
  is. Enter on a task's reference alone (`task:4`) opens the task instead of searching. The search page has a panel per
  source with hits, in the server's order, its count in the header (`newest 20` when the source has more). A hit is a
  row: where it opens (its ticket or chore with the run that said it, a chore run as itself, `chore:deps#2` opening its
  page, the tick that decided it, or a task, `task:4`, or its run that said it, `task:4#5`, over the task's first line
  in `muted-foreground`, cut to the column), its label as a chip (a chore run's status as
  its dot and word, as its chore's page lists it), the snippet with the query's words marked on the accent's tint
  (`bg-accent/20`, `src/lib/search.ts`), and its age. A snippet links nothing, since it may cut a URL short. While the
  next query's hits load, the last ones stay, dimmed to 60%. While empty, the field's end also holds the jump palette's
  keys (`⌘K`, `Ctrl+K` off an Apple keyboard) in a keycap that opens it.
- **The jump palette** (`JumpPalette`, `src/components/shell/jump-palette.tsx`) jumps to a ticket from anywhere: `⌘K`
  opens and closes it, from a text field too, as a `Dialog` in the window's top sixth over the canvas at 70%. Its field
  is over the tickets viewed last, newest first, without the one on screen, so `⌘K` Enter goes back to the ticket
  before it; typing narrows them by key or title and lists the other tickets that match under them, at most 20 then
  `+N more` to the tickets page, and with none, the journal's search for the words. A row is the key, the title, where
  the ticket stands now in its state's color (waiting on you, its plan waiting, its run) or its phase muted, and for a
  ticket viewed, how long ago. What was viewed, a ticket's page or its plan's, is this browser's alone: localStorage
  (`src/lib/recent-tickets.ts`), never the journal, and a ticket the journal no longer holds leaves it.
- **The review dialog** (`ReviewDialog`, `src/components/shell/review-dialog.tsx`) asks for a review from anywhere:
  `R`, with no modifier, from anywhere but a text field or the plan editor (the rule `/` follows), or a GitHub PR's URL
  pasted outside a field, which it fills in, opens it; on a PR's page, `R` fills in that PR's. It never opens over
  another dialog. It is a `Dialog` placed as the jump palette is, titled `Review a PR` in a panel's header, holding the
  reviews page's form (`ReviewRequestForm`), one component for both so they cannot drift: URL, notes, the reviewer
  row ending on the primary `Review`, and one quiet line saying the review is a draft. The focus starts in the URL
  field, or in the notes once the URL is filled in. A request that goes through closes it and opens the PR's page; a
  refusal keeps it open, its `Notice` naming the guard. What is written outlives closing it, kept in the tab's
  `sessionStorage` (`src/lib/review-request-draft.ts`) until a request goes through or the operator signs out.
- **The ticket dialog** (`TicketDialog`, `src/components/shell/ticket-dialog.tsx`) starts a ticket from anywhere: `T`,
  with no modifier, from anywhere but a text field or the plan editor (the rule `R` follows), opens it, never over
  another dialog. It is a `Dialog` placed as the review dialog is, titled `Start a ticket` in a panel's header, holding
  the tickets page's form (`StartTicket`), so they cannot drift, with the focus in the key field. A ticket that starts
  closes it and opens the ticket's page; a refusal keeps it open, its `Notice` naming the guard. Beside the button,
  a `Checkbox`, `Plan it first`, starts as `policy.plan` is in Settings, naming it while it does; it is sent only when
  it differs from the policy, as `--plan` or `--skip`. Under the key, a
  `Disclosure` opens a row for each of the ticket's agents in the order the ticket meets them, planner, worker,
  reviewer, each a persona menu and a model menu (`ModelPicker`) naming its default until one is picked; the picks go
  with the start as the ticket's overrides, and folded, the disclosure says how many there are.
- **Signed out**, the whole page is the sign-in card, centered on the canvas: no shell, nothing from the journal.
  Signed out by a 401 to an action, the card says under its heading, in `status-failed`, that the action was not sent
  (`unsentQuery`). A reply being written outlives the page that held it: the reply form keeps what is written, with its
  submission id, in `sessionStorage` per ticket or chore until a reply is recorded (`src/lib/reply-draft.ts`), so after
  signing in again it is still in the box. Signing out on Settings drops every draft in the tab, so the next person to
  sign in at it sees none.
