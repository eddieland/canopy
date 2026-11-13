# canopy web UI: design

The visual and interaction rules for `ui/`. Normative, like `docs/design/`: if a component and this file disagree,
this file wins until it is changed in the same PR. How to work in `ui/` is in `AGENTS.md`; why it exists is D079.

What belongs here is what `docs/design/README.md` says belongs in the design: a rule a page follows, a promise the
operator relies on, and the reason for it, in a sentence. How a component does it, its file, its exact sizes, and its
edge cases live in the code; what a page shows, in the guide. An entry names its component once, so a reader can find
the code, and says the rule the next page must keep. A section past about 100 lines is pruned before it grows.

## Direction

An operations inbox: a control room's at-a-glance state, kept calm enough to read a worker's words and answer
them. Data sits in monospace readouts on quiet surfaces, separated by hairlines, on a plain canvas. One accent color
marks what is live, selected, or the action to take; what is selected in a page sits on its tint. Each section of
the nav has a color of its own, for a little fun and a sense of place: its icon, the nav's highlight and label on it,
and the trail over its pages wear it, and an aurora of them runs under the header. Status color is reserved for
state, and a counter wears the color of what it counts; section colors never mark state, and nothing else is colored for
decoration, but the fun's own (Fun, below). By default both themes' neutrals carry the accent's indigo hue, so the
canvas has color of its own; each can wear another palette instead, picked apart (Themes, below). Dark is the one the
operator lives in; neither is the lesser theme. The directions weighed against this one, an instrument panel among
them, are in `docs/ui-explorations/2026-10-08-style/`.

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
| `depth-chip`, `-selected` | A chip's and a selected row's ink, `shadow-chip` and `shadow-selected`: none by default. |
| `control-line`, `-quiet` | A field's and outline button's line, and a secondary one's (`border-control`, `-quiet`). |
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
| `check-1` to `check-4`, `check-other` | The CI page's checks by rank, and the rest; the Connectors page's sources. |
| `wait-1` to `wait-4` | How long something took, the quickest first: Reviews' first reviews, Health's run lengths. |
| `answer-pass`, `-fixed`, `-held`, `-na`, `-unanswered` | The checklist page's answers: an item's bar, and by week. |
| `proposal-change`, `-decline`, `-ask` | A feedback plan's proposal chip: what it does with an item, never a state. |
| `syntax-key`, `-string`, `-number`, `-literal` | Agent output's JSON keys, strings, numbers, literals; code. |
| `code-chip`, `code-size` | Inline code's chip, a tint of its own ink, and code's size against its line (Rich text). |
| `flair-*`, `buddy-*`, `rave-dark` | Fun's own colors (Fun, below), each named in `tokens.css`. Never a status. |

Rules:

- **No raw colors outside `tokens.css`.** No hex, `rgb()`, `oklch()`, Tailwind palette classes (`bg-zinc-800`,
  `text-white`), or arbitrary color values. `npm run lint` fails on them.
- **No `dark:` in components.** Both themes are first-class and come from the same tokens. If a component looks wrong
  in one theme, the token is wrong: fix the value in `tokens.css`, for that theme. The lint fails on `dark:`.
- **Text reads at 4.5:1** (WCAG AA for small text), in both themes and every palette: every token used as text on
  `background`, `surface`, and `surface-raised`, and each status on its own tint up to 20%, in a selected row too, and
  the nav's active label on its highlight. `src/styles/tokens.test.ts` measures every pair from `tokens.css` and fails
  below it. Text is never faded with `opacity` to look quieter: that is what `muted-foreground` is for, and an opacity
  under it drops below AA. Only a disabled control, and a state that passes (search's last hits while the next load),
  dim. The ticker's `flair-*` colors are decoration, not held to it.
- **Status colors** work three ways, in both themes, on `surface` and `surface-raised`: as a dot (`RunDot` in
  `src/components/status.tsx`), as text, and as a tint (`bg-status-blocked/8` behind a question). Map a state to its
  classes through a `Record<State, string>` written out in full, never by building a class name from a string:
  Tailwind only generates classes it can see.
- **Worktree states** borrow the run colors (`src/lib/worktree-state.ts`): `working` is `status-running` (it does not
  pulse; the run it names does, on the runs page), `held` is `status-stopped`, `dirty` is `status-blocked`, `broken`
  is `status-failed`. An `idle` slot is a hollow ring in `muted-foreground`: nothing holds it, so no status color
  claims it.
- **Section colors**, one per section, each taken from something its page is about, so the color says what the page
  is for (`src/lib/sections.ts`): Attention rose, an alarm light; Tickets sky, a message bubble; Tasks chartreuse, a
  new shoot, yellow-green before it is `status-running`'s emerald; Epics fuchsia, a transit map's route line, one line
  tying many stops together; Pull requests violet, the purple a merged PR turns; Workspace indigo, the night shift;
  Chores orange, a hi-vis vest; Reports gold, coins; Memory pale azure, the forget-me-not, which shares done's hue at
  no cost since its page shows no run state; Settings slate, the machinery, worn on its trail alone since it sits in
  the rail's footer. A new section takes a color the same way, and stays apart
  from its neighbours in the nav and from the status colors on its own page; nine nav hues, five statuses, and the
  accent leave the wheel full, so a new one may mean moving another. They go on the nav's icons, highlight, and active
  label, the hairline beside the pages open under a section, the first step of the page header's trail, and the
  header's aurora and name, and nowhere in a page's data: there a color is a state's. A page in no section (the 404)
  takes the accent.
- **Fills** color a chart's series and nothing else, in the report pages' charts and their legends, and are fills,
  never text, so a legend's words are `muted-foreground` beside a swatch. Each reaches 3:1 on `surface` in both themes
  and every palette, WCAG's bar for a graphic, which `tokens.test.ts` measures. The spend series (`src/lib/spend.ts`)
  color a kind of agent run, or the sessions outside canopy, one color per kind across Reports; idle overseer spend is
  the overseer's hue, lighter, so it reads as part of it. The check fills color the CI page's red checks by their rank
  that window, the most often red first, never by name, the rest in `check-other`, the dry run's neutral; their hues
  sit apart from the spend series and the status reds and greens, so a check never reads as a kind of run or as a
  verdict. The wait fills are a ramp of cool hues by how long a first review waited, the quickest lightest, never a
  status color, so a slow review never reads as a failure; the Health page's run lengths take the same ramp by their
  share of the timeout, a run at the limit in `status-failed`, since it was stopped. The answer fills are the one set
  where green and red mean what they say: a pass reads as passing and a held item as the failure a run left it. The
  context fills draw a transcript's context chart: a neutral with the canvas's hue in it for what a call carried, a
  cyan for what it added, each at 3:1 on `surface-raised` too, the picked call's.
- **Adding a token**: define it in both `:root` and `.dark`, expose it in `@theme inline`, and add a row above. Check it
  on both themes' surfaces before using it. A neutral, or a color drawn in one, is set again in each palette's rule.
- **Palettes.** Lavender is light's default and indigo dark's. Each other palette is a rule in `tokens.css` that sets
  the neutrals and the accent over the default's, keyed on `data-light-palette` or `data-dark-palette` on `<html>`,
  and `tokens.test.ts` measures every palette `src/theme/palette.ts` lists. A scheme with an accent of its own wears
  it; the others take one that suits the canvas. A light canvas is never grey, which only looks dim. Every other hue is
  the same in all, so a component never knows which palette it is on, and an accent is read through its token, never
  assumed indigo; where a scheme's own bases would drop a hue below 4.5:1, the bases move, never the hue. A palette's
  accent is darkened or lightened until it reads as text there, on its own tint, and under `accent-foreground`, and
  sets `ring` with it. A scheme whose accent would pass for a status wears another of its colors, as Gruvbox wears its
  purple, not its orange, and a green canvas never takes a green accent. A scheme whose bases would have to move until
  it matched another palette is left out, as Nord's dark is.
  A palette sets its character too, beyond color, from a few closed choices in the same rule, so a component still
  never knows which it is on: its corners (`--radius`), its `edge` (a hairline, or none, where panels stand apart by
  their lightness alone), its depth (a soft shadow in the canvas's hue, a hard one with no blur, or, on black, where a
  shadow does nothing, the accent's glow), and its face (`--face`: interface text in Plex Sans, or in Plex Mono, as an
  editor sets it). Spacing, sizes, and layout never change with a palette, and neither do the status colors; only the
  mono face reflows text, since it runs wider, so it stays with the few palettes that are an editor's own look, and
  there draws every line a step smaller, at 15/16 of the size asked for, in the same line boxes, so no line changes
  height. The guide keeps the default faces under every palette, since pages of prose read worse in mono. The one
  other face that reflows is Pulp's display face (`--face-title`), on a section's own page title alone, a fixed name,
  never a title from the data, so no line it sets wraps differently.
  A palette may ink the page further from knobs whose defaults draw nothing: a panel's, a bubble's, a chip's, and a
  selected row's outline and drop, a field's and an outline button's line in ink, a tone printed on the canvas, the
  primary action pressed into its shadow, a page title dropped in its section's color and lettered, a bubble's balloon
  tail, and a starburst where a cleared item drops its leaf. Each is a shadow, a transform, a background, or drawn
  beside its box, so it takes no room, and a texture is clear where text sits. Pulp, a comic in four-color print, takes
  them all; both its sides ink by the same rings, dark's line its cream.
  A palette may also give the shell's signature a form of its own, the first place it is felt: the aurora (a gradient
  hairline, a stepped bar of solid blocks, a print strip of those blocks, or a line that blooms), the name (the
  aurora's gradient, on a solid block, on a tilted plate, or glowing), and the nav's highlight (a tint and a bar, a
  solid block with the active item inked in the canvas's color, or a tint with the icon lit). On a block, a count
  beside the active item sits on a plate of that ink, where its status color reads. Each form takes the room the
  default does, so a switch moves nothing, and what a form draws past its box stays clear of what is beside it.
  A palette may tune its section colors too, muted toward a scheme's own set or turned up, but each keeps its hue's
  family, which says what its page is for: a rose stays a rose, a gold a gold. Each still reads at 4.5:1 there, and
  stays apart from the status colors and the palette's accent.
- **shadcn names** (`primary`, `muted`, `card`, `popover`, `input`, `destructive`, ...) are aliased onto ours so
  generated components render unchanged. New code uses our names. shadcn's own `accent` (a hover tint) is not
  aliased: here `accent` is the brand color, so replace `bg-accent` hover tints in generated code with
  `bg-surface-raised`.

## Type

- **IBM Plex Sans** (variable) for interface text, **IBM Plex Mono** (400, 500, 600) for data: one family, so the
  two sit together on a line. Self-hosted and preloaded, so text never paints in a fallback face; a new weight needs
  its own import and a place in `PRELOAD_FONTS` in `vite.config.ts`. A palette may set interface text in Plex Mono
  too (Palettes, under Tokens).
- **Bangers**, a comic letterer's caps, is the one display face, Pulp's, for a section's own page title alone, never a
  title from the data. It is drawn a fifth larger than the size asked for, so its caps stand as tall as a sans title's
  ascenders, in the same line box; it has one weight, declared for every weight so the browser never fakes a bold. No
  other face is loaded.
- `readout`: monospace, `tabular-nums`, slashed zero. Use it for every counter, timer, cost, id, and timestamp, so a
  changing number keeps its width.
- `panel-label`: small uppercase monospace in `muted-foreground`, the label above or beside a value.
- Sizes: `text-xl` page titles and the spend's totals, `text-sm` body, `text-xs` secondary and data-dense rows, and
  `text-2xs` (11px, defined in `tokens.css`) for the smallest print: a chip, the stream's state, the rail's labels and
  spend windows, and a `panel-label`. A document, long-form prose, has one step of its own, `text-base`, through its
  utilities alone (A document, under Primitives); rich text's `#` and `##` headings are the one other place it appears.
  Nothing larger, but a counter's value (`text-3xl`), and nothing smaller or between the steps: no arbitrary sizes
  (`text-[0.625rem]`). Code is the one size set against its line, not a step (`text-code`, Rich text).
- **An icon is the size of the text it sits with**: 16px (`size-4`) beside `text-sm` and in a button of the default or
  `sm` size, which sets it; 12px (`size-3`) beside `text-xs` or smaller, in an `xs` or `icon-xs` button and a segmented
  control, which set it too, and as a link out in a row. Nothing between, but a checkbox's tick, which fills its box,
  and nothing larger, but the page header's guide book, which sits with the title.

## Shape and space

- Hairlines: 1px `border` everywhere inside a panel. A panel, and what floats over the page, draws its palette's
  `edge` instead, a hairline but where the palette draws none.
- Depth is used sparingly, in three places and nowhere else: a faint lift under a panel and a counter
  (`shadow-panel`), a shadow under what floats over the page (`shadow-float`), and one under the primary action, the
  default button (`shadow-action`). Each is the palette's (Palettes, under Tokens), so its form changes with it, and
  nothing inside a panel casts one but a pressed segment's `shadow-xs`, and a bubble, a chip, and a list's selected row,
  which cast none but on a palette that inks them.
- Radius: `rounded-md` for panels, buttons, and fields, `rounded-sm` for chips and nav items, `rounded-xs` for a mark
  smaller than a line of text, a checkbox or a slot's square, from the palette's `--radius`. The scale is in
  `tokens.css`; no arbitrary radius, which `npm run lint` refuses.
- **The shell**: a 3rem header, a 13rem side nav, content capped at `max-w-shell` with `p-6` and `gap-6` between
  blocks. The header stays put and only what is under it scrolls (`page-scroll`), so a scrollbar, or the gutter kept
  for one, sits beside the rail and the page, never beside the header. The side rail runs the full height of the page,
  and what it holds sticks: a column as tall as the window under the header. Printed, the shell is not held to the
  window and shows the page whole; a screenshot test does the same by growing the window to the page.
- **Skip to content** is the first stop the keyboard reaches under the header (`SkipToContent`): a link, unseen until
  it has the focus, that moves the focus to the page's `main`, so the next Tab is the page's own first stop rather than
  the rail's search, a dozen nav items, its runs, and its spend. It moves the focus by script: `#main` under the base
  path would be another page's address.
- **The rail** (`src/components/shell/rail.tsx`) holds two groups: at its top, the search box, the nav, and what is
  working now; at its foot, the spend, then a footer with the version, the guide, and Settings. The nav lists the
  sections by how often the operator opens them (`SECTIONS` in `src/lib/sections.ts`), what they work in first;
  Settings, opened least, is in the footer, since each nav item is height the sticky part has none to spare of in an
  800px window. The pages under a section open under its item while it is the section shown, `muted-foreground` rows
  on a hairline in the section's color, so the rail says where a page is; elsewhere they stay folded, so the nav keeps
  its nine rows. Each nav item says on hover what its page holds, and each spend window what it covers. What is
  working is every agent run running, then the worker runs waiting on the operator's answer, each oldest first, a
  ticket's latest run alone: its state's dot, what it works on, how long it has run (or `waiting on you` in
  `status-blocked`, the whole row on a question's tint so it shows from across the room), and under it what names it,
  opening the run's page; at most three, then `+N more` to the page of the rest, so the sticky part fits an 800px
  window. The spend is the last 24 hours and the last 30 days, from the stream, two rows set alike so neither reads as
  a different kind of figure, the figures right-aligned readouts so they line up at four digits as at one; the 30 days
  is shown nowhere else but what Fun buys with the lifetime total. The foot sits at the foot of the sticky column, so
  at the window's foot however long the page; in a window too short for the rest, the top scrolls on its own. The room
  left between the two groups is one gap, and Sprig's slot (Fun, below).
- **Narrower than `lg`, the rail is a strip** (`useRailMode`) of the nav's icons, each named on hover and to a screen
  reader, each count one number on its icon's corner, Attention's in its most severe item's color, since a narrow
  window is under it and a whole rail there left a list too little room. A button atop the strip opens the whole rail,
  footer included, as a sheet over the page, in its search box, so `/` opens it too; a link followed or a search sent
  from it closes it. The breakpoint is the viewport's, as the rail's place is the window's; every layout step inside
  the pane is its own width's (Primitives). The UI is made for the operator's window, about 1720px wide
  (`PRODUCT.md`), where its screenshots are taken. Down to about 820px it holds up, the rail a strip, and two
  screenshots hold how it looks there. A phone's window it does not.
- **Sizes are in rem, and rem grows with the window**: the browser's size up to a 1600px window, rising to a quarter
  larger at 2560px (`font-size` on `html` in `src/index.css`). Write sizes in rem so a large screen scales them; px
  only for hairlines and the like. Breakpoints are not scaled.
- **Wide screens use the width** from `2xl`: the attention list widens, and a detail page puts its thread or main
  content beside the rest. The source keeps the narrow order, which is the reading order; the grid only places that
  content in a second column, over rows whose last is `1fr`, so a long thread leaves no gaps between the panels beside
  it.
- **The header** carries, after its name, the stream's state (and `mock`) and the ticker (Fun, below); then at its end
  the loop's pause and Tick now, the readouts, and the theme toggle, in three groups with a hairline rule between each.
  Every readout that opens a page has a hover card of it; the theme toggle has one of the shown theme's palettes,
  which stays open through the reveal so palettes can be tried in turn. The readouts hug their text, so each rule sits
  midway. The latest tick's readout links to its page, its status in `status-failed` when it failed or was abandoned,
  and before the first says `no tick yet`, so a fresh workspace does not read as a quiet one.
- **The stream's readout** (`StreamReadout`) sits beside the name, not with the readouts at the end, so a drop moves
  nothing: its word hugs its text, in a pill with a dot, and only the ticker's window gives way when it changes. `live`
  in the accent while open, `opening` and `retrying` muted while it connects or has just dropped, and once down past
  the first retry's wait, `down · 2m` in `status-blocked`. Only `canopy loop` serves the UI (D073), so a stream that
  stays down almost always means the loop stopped, and the page says so rather than look live (`useLoopDown`): after
  10s a band heads the content column saying the loop isn't answering and how long ago the page last heard it; Pause
  and Tick now wait; the Working rail dims to 60%; and an empty attention list says nothing needed the operator as of
  the drop rather than celebrate. What is on screen stays, and all of it leaves the moment the stream opens again.
- **The nav's counts.** The Attention item shows how many items it lists, on every page, split by severity: broken in
  `status-failed`, waiting on the operator's answer in `status-blocked`, the rest muted, each only when there is one;
  never in the section's rose, too near the failure color to tell apart at that size. Since color alone tells the
  numbers apart, they are said in words on hover and to a screen reader. That split is the nav's alone: the list's
  panel header gives the whole and does not say it again. The Memory item counts the proposals waiting on the operator,
  in `status-blocked`, and the Reviews item the reviews with a result the operator has not seen, in the color of the
  worst finding among them; each is said in words, and shows nothing while none waits. What they have seen is the
  journal's (DESIGN §22): a review's page marks it as it shows the result, and a new review's row, wherever a list shows
  it, has a dot in `accent` after its verdict.
- **The pause** is the header's standing action, since it is about the loop, not a page's subject: a ghost Pause
  button while the loop runs; paused, `paused · 3m` in `status-blocked` (the loop waits on the operator) and a Resume
  button, one width in both states. It has no `Notice`: what it did is the state it shows, which the stream also sends
  when the CLI pauses. A failure colors the button `status-failed`, with the reason on hover and in an `sr-only` alert.
- **Tick now** stands after the pause, a ghost button beside the latest tick's readout, which shows the tick it starts.
  It is disabled while the latest tick runs, and from the click until the tick it asked for starts, which the readout
  and the logo show as starting meanwhile. Like the pause it has no `Notice`, and a failure looks the same.
- **The budget's readout** (`BudgetReadout`) is the local month's spend against the monthly budget, while one is set: a
  wallet's icon and the percent spent, muted while on budget, in `status-blocked` once the month's pace heads over, and
  in `status-failed` once it is over, the spend page's words for it as its accessible name. Short of `2xl` the icon
  stands alone in its color: the ticker needs the room. It opens the spend page.
- **The host's readout** (`HostReadout`) is the machine the loop runs on: a server's icon and `host ok` in muted
  readout type, or its worst pressure in two words (`disk low`, `host busy`) in `status-blocked` while worth a look and
  `status-failed` past what canopy works with. Under `lg` the icon stands alone in the pressure's color, its words its
  accessible name. It opens the system resources page, in no section. It shows nothing until its first read lands, and
  its read is not on the stream, since none of it is in the journal.
- **A band heads the content column** for what every page must say: the notice to workers (`NoticeBanner`), while one
  is in force, on the `status-blocked` tint, since every run waits on what the operator said, with ghost Edit, Renew,
  and Clear, since the header has no room for a sentence; a chore over its finding limit (`ChoreLimitBanner`, under its
  page's title), on the same tint, since only the operator can settle it, saying by how much and the two ways out, with
  no button, since both ways out are the operator's words; and changes asked of a plan that no planner has started on
  (`ChangesAsked`), on the `status-running` tint, since the loop acts on them next, never a muted line a request can
  hide in; and on the system resources page, what is under pressure, on the worst pressure's tint, each concern in its
  own pressure's color with what it costs and the way out under it, since the operator arrives from the header's
  readout to ask exactly that.
- **Agent memory** (docs/design §28) shows only while a tier is on, and always says each tier's mode in words, never by
  color alone, so recorded memory is never taken for memory in use: the header's readout, `memory: recording` or
  `memory: in use`, opening the memory page, which is in no section; and a tier's band heading its panel, a chip naming
  the tier and its mode and the server's sentence on what reads it. What a worker wrote is `MemoryText`: plain text,
  never `LinkedText`, since a link in a note would be a worker's link read as canopy's, with each character that hides
  text named on a `status-failed` tint, so it is seen. A digest is the prompt's own text in monospace, labelled `would
  be served at use` while recording. A memory's row leads with its standing, a dot and its word in a run state's color
  (`memoryStand`): `wrong` and `due` for a lesson that calls for the operator, `pending`, `active`, `superseded` or
  `invalid`, and `recorded` for one in force under a tier that only records, which no run reads, so a row never reads
  as in force under a `recording` band; a proposal's says the time left in its place. The memory page leads with what
  waits on the operator, the Proposals, then Lessons, the pinned ones first as runs are served them, then Ticket notes,
  a row a ticket opening to its notes, read only then; a filter field and a repository picker narrow all three, and a
  `history` chip lists each panel's decided and retired memories under the rest, with no verbs. The verbs on memory
  (`src/components/memory-actions.tsx`) sit in a line under a row, `xs` as a row's buttons are: under a proposal
  `Promote as written`, outlined, which saves at once, since most proposals need no edit, then a muted ghost `Edit and
  promote`, which opens the form, but on a private ticket's run's proposal, whose words may hold what the operator kept
  off the tracker, and on one that would replace a lesson in force, where `Promote` opens the form and what it says
  first; `Renew` under a lesson, outlined once it is `due` or `wrong`, since only then does it ask for a decision; and
  `Forget`, the rarest verb and one that cannot be undone, last, muted at rest and `status-failed` while hovered, asking
  for the memory's ref typed out as a ticket's Forget asks for its key. A lesson that asks nothing shows its line only
  while its row is hovered or holds the focus, as a row's copy button does, and always on a touch screen. A row can
  leave once its verb is done, so what it did is said once under the panel's header, and only a refusal stays under the
  row. A memory with more than one version says so on its line, and `Show versions`, a `Disclosure`, opens them, read
  only then. Purge is the one memory verb the page leaves to the CLI: a muted line under every panel names it, with a
  `Copyable` that copies the verb alone, never an option, so a paste purges nothing until the operator names what.
- **Reload** stands before the pause only while the server serves a newer build of the UI than the page loaded
  (`NewerBuild`): a ghost button on the accent's tint, the action to take without a fill that outshouts the ghost
  buttons beside it, saying on hover why and that unsent text is lost. It never reloads on its own, since the operator
  may be typing.
- **Pages are a `PageHeader` followed by `Panel`s** (`src/components/panel.tsx`). A panel's title row is `PanelHeader`,
  on `surface-raised` at half strength with its label in `foreground` at weight 500, so it stands apart from the rows
  under it; half, so a ghost button's hover in it still shows. A `sticky` header stays at the top of the page while its
  panel scrolls under it, opaque so the rows do not show through. A page's main list is named for its page's noun, and
  a panel for its noun, never for how it is cut, and counts what it lists: a list of runs is Runs on every page, and how
  a page filters it is a label in its header, not its name. A title wraps inside an unbroken word, since it can be a
  pasted URL. A description is `text-balance` up to `max-w-3xl`, and prose inside a panel keeps the same measure
  however wide the panel, as the guide's article and a plan do.
- **One heading ladder**: a page has one `h1`, its `PageHeader`'s title; every panel's label is an `h2`; what heads a
  part of a panel is an `h3` in `panel-label` type, and a part of that an `h4`; a plan's own headings start under its
  panel's, its `#` an `h3`. No level is skipped, so a screen reader's list of headings is the page's outline;
  `e2e/headings.spec.ts` holds every route to it. A list of links named by its region is not a heading.
- **A detail page leads with what it is about.** Its title is its subject's, after its reference in a muted monospace
  (`PageHeader`'s `subject`): `run:39 Debounce search input`, a review's `review:4 acme/web#88` then its PR's title.
  With no subject, the reference alone is the title. Its description is that subject's state, a line of facts
  (`src/lib/descriptions.ts`), so no two pages of a kind say the same thing there; what every page of its kind shows,
  the same each time, is its `help`, on the title's hover, as the nav's items say what their pages hold. A ticket is
  named one way in every identity panel that names one (`TicketField`: its key, then its title). A tick's page steps
  to its neighbours from the right of its title's row (`TickSteps`), through every tick by id; at an end the button
  stays, disabled, so the pair never shifts.
- **One home per fact.** What a page says, it says once. Its subject's own name is its title, so the lists under it
  leave it out (`ticket={false}`, `ownPr`). A PR's phase is its title's chip, not a field too; a ticket's phase is its
  Work panel's field, not its description too; whether a ticket is private is its title's chip. The pages of what runs
  and ends put each fact in the same home: the state, a run's kind, and its ticket in the description, so the identity
  panel's header is its name alone; a chore run's chore and a task run's task in the trail; the session in the
  transcript's header; and the paths in the identity panel.
- **A detail page has one skeleton**: what it is, then its thread or main content, then the lists that support it.
  First the identity panel, its subject's fields; its actions sit in that panel's foot, under a hairline, never in a
  panel of their own above the content, but for a ticket's, which follow its reply (The answer, below). What runs and
  ends keeps one order there, the page's answer first: `summary`; then what came of it; `when` (`WhenField`), started,
  ended, and how long it took in one field; `spent`; then the paths. A run given a checklist has its answers in a panel
  of their own under that one, a row an item, too many for a field, `held` in `status-blocked`, since a reviewer reads
  its reason under it. A worker's or a task's run that ended has its Diff next, a panel per repository that sums up
  rather than shows: the range, files, and lines in its header's readout, the files with theirs under it, then its
  commits (`RunCommits`), each a short id linked out through the PR, its subject as text, and canopy's marks as chips,
  and the diff's file panels, each an h3 naming its file, only once `Show diff` opens them, read then, so the
  transcript stays on the first screen; a sentence where a diff is missing, never an empty panel. What a run pushed
  after a list is part of that change, so it is a scope of its repository's Diff, not a panel beside it: a segmented
  control, `after the list` and `whole run`, opens on the stretch, a dot in `answer-fixed` marks each file it touched,
  and a line under the files names its commits, so the answers and the fix are read together and the stretch reads as
  inside the run. A scope with no diff to draw keeps the disclosure, disabled with why on hover, so the control never
  shifts. Then
  the thread the operator came to answer, with its form, then the ticket's actions; a page with no thread has its main
  content there instead: a transcript, a chore's open findings and runs, a tick's decisions, a review's findings and
  diff, a PR's reviews. A chore's notes are a thread nothing waits on, so they follow
  its main content. Then the supporting lists: runs, decisions, spend, and a ticket's memory last, the least read. So
  in a narrow window a ticket's reply is reached before its runs, and the attention detail reads in the same order. An
  action over a whole list sits in that list's panel header. A ticket's plan is on a page of its own,
  `/tickets/$key/plan`; the ticket's page has its card (`PlanCard`): the plan's reference and status chip (`PlanChip`:
  `waiting on you` in `status-blocked` while the plan waits on the operator, `changes asked` in `status-running` while
  they wait on the next planner, else its status), the run that wrote it and its open comments as fields, and in its
  foot `Approve`, the primary, while the plan can be approved, then `Open plan`, outlined. No `Approve` is offered
  without the choices it takes in view: a plan's open decisions are asked on the card as on its page (A plan, below),
  between the fields and the foot, and the line beside the button says what approving does with them. A ticket whose
  plan waits on the operator leads with the card, above its Work panel, since the plan is what they came to answer;
  otherwise the card follows the lists. Where it sits is settled as the page opens, so a plan approved meanwhile leaves
  its card where it was read. A review's run is on a page of its own too, with a run's skeleton; the review's page is
  its results, and links there from a `run` field.
- **Every page header opens with its trail**, a breadcrumb in `panel-label` type: the section's name in its color, then
  the pages between it and this one, each a link ending in a small chevron, pointing at the title. A page in no section
  names itself there in the accent. A parent is a journal name, so it keeps its case and stays muted until hovered. The
  title is the trail's last step, so the trail never repeats it. The trail follows the URL, not the journal: a run's
  page is under Workspace's Runs, not its ticket, which its panel links. What qualifies a page, `private` or `dry run`,
  is a `Chip` beside the title, never a word in the trail.
- **A book at the header's top right** opens the guide's page about the page shown, at the heading about it when it has
  one, named `The guide: Runs and worktrees` on hover and to a screen reader: a ghost `icon` button sized to the title
  beside it, so it is there when wanted and quiet when not. Which page each route opens is `PAGE_GUIDES` in
  `src/lib/guide.ts`, keyed by route id, so a new route fails the type check until it names one.
- **The tab** names the page too (`pageTitle` in `src/lib/page-title.ts`). A tab is narrow and cut from the right, so
  it leads with how many attention items block work, when any do, then the page's name, then `canopy`:
  `(3) ABC-102 Export reports as CSV · canopy`. The count leaves out what only waits on someone else and chore findings,
  which report rather than block (`blocking` in `src/lib/attention.ts`): a count that never falls to zero while PRs sit
  in review would stop meaning anything.
- **The tab's icon** is the header's mark in the accent, since a pinned tab shows no title. While anything blocks work,
  a dot on its top right corner, cut out of the ring, wears the most severe item's color (`faviconDot` in
  `src/lib/favicon.ts`). It is static: a tab that moves pulls the eye from whatever the operator is reading.
- **The nav wears the sections' colors**: every item's icon in its own, and the active item's highlight a tint with a
  bar down its full height, its label at medium weight in the section's color. On a page under a section, the
  highlight is on that page's item, and the section's label stays in `foreground`, untinted. Light's section colors sit
  near 4.5:1 on the bare canvas, so on their tint the label is shaded toward black (`nav-label-shade`). In a page,
  **selected is the accent's tint**: the selected inbox row and the runs page's chosen filter. Hover stays
  `surface-raised`, so selected and hovered differ.
- **The aurora**: a hairline along the header's foot, over its border, fading through the nav's colors in the nav's
  order. It is static.

## Fun

canopy should be a little fun to use (PRODUCT.md): the header's ticker, Sprig at the foot of the rail, the empty inbox
and the leaf a cleared item drops (an approved plan drops one too, and so does a review draft once published, not
staged), the lightswitch rave, and 2048, typed anywhere but a text field. An epic's `n of n entries filed` lights and
drops a leaf the first time this browser shows its breakdown full, and never again. Fun is ancillary, so this design
holds only the rules it all keeps; what each one does is written in its code. None of it is journal text.

- **Fun never covers data, and never squeezes it.** Each has a place of its own in the layout. Where the window
  leaves it too little room to be read, it steps out entirely, rather than shrinking, clipping, or sitting on
  something; its room stays, so nothing beside it moves. The fit is measured as the layout changes (`useFits` in
  `src/hooks/use-fits.ts`), before the first paint, so what does not fit never flashes in. Three exceptions, all the
  operator's call: Sprig may stand over the foot of the rail's working runs by 40px rather than step out, taking none
  of their clicks and offering tips there only when clicked; the rave covers the whole page, taking no pointer, hidden
  from a screen reader, not printed; and 2048 opens over the page as a dialog, only when typed, and Escape puts it
  away.
- **Fun is never colored as state.** Its colors are its own tokens (`flair-*`, `buddy-*`, `rave-dark`) or the accent,
  never a status color, so nothing in it reads as a run's state.
- **Fun never fakes state.** A cleared item's row leaves after the item is already gone from the list and its count.
  The last one's plays out too, beside no detail, before the all clear rises in; under reduced motion, or on a page
  that reads the list empty, the all clear is there at once, and plays nothing.
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

- Route changes cross-fade through the `<ViewTransition>` around the outlet. The old page stays until the new one is
  ready, because navigations run inside React transitions. A transition that redraws part of a page, as a transcript's
  search does at each key, is typed `in-page` (`inPage`), and the outlet leaves it be.
- A page's blocks rise in one after another (`stagger` on the page column), and so do the attention list's rows, the
  Working rows, and a conversation's bubbles. Any other list's rows arrive with their panel, as one block. A row or
  bubble the stream adds later rises in on its own. A bubble pops from the corner nearest its side. A reply's `seen`
  pops in once when a tick reads it while the page shows it, never on a page that opens on it already read.
- Counter values are odometers (`RollingNumber`): each digit rolls to its new value. The value is in the text once,
  for screen readers and tests; the digits are drawn by CSS.
- The nav's highlight is one element that slides to the active item, changing into that item's section color as it
  goes.
- The header's logo is alive: its dot breathes while the stream is live, an arc sweeps its ring while a tick runs or
  one Tick now asked for is starting, and a ripple leaves it when a new tick appears.
- The theme toggle reveals the new theme as a circle growing from the button, and its new icon spins in.
- Skeletons shimmer: a light passes over them.
- Fun moves as its code says, within these rules. A cleared item's fold is the one animation that fills forwards:
  the row is let go once it has played.
- A toast rises in from below and fades out.
- A row a page is opened at by its anchor (Loop settings' `#key`) lights in the accent's tint, which fades once.
- What floats over the page fades in, growing a little from where it opens (`animate-float`), and fades out quicker.
  A sheet slides in from its edge. A menu only floats in: it goes at once on a choice, so the focus the choice moves
  is not left waiting on it.
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
  holds that height only while its read is pending: read, it is as tall as what it holds.
- A skeleton (`PanelSkeleton`) shows only while there is no data at all, and only while the read is pending: once it
  has failed, a Notice takes its place at its height (`PanelLoading`). A refetch or a stream update keeps what is on
  screen.

## Themes

Light, dark, and system, stored in `localStorage` under `canopy-theme` (absent means system) and synced across tabs.
The blocking script in `index.html` sets the `dark` class, `color-scheme`, and `data-theme` on `<html>` before first
paint; `src/theme/store.ts` keeps them current afterwards. Change one, change both: `theme-script.test.ts` runs the
inline script and checks it against the store's key. Each theme's palette is kept the same way (`src/theme/palette.ts`)
and set on `<html>` by the same script. What else the operator sets for this browser alone, the key that sends a
reply, each list's order, and each fun setting, is kept under a `canopy-*` key of its own, synced across tabs, never
in the journal.

## Primitives

Every list and detail page is built from the same few pieces, so a new page lines up with the others without anyone
measuring. A page that needs something they do not offer extends them here first; it never builds a row, a field
list, an empty state, or a skeleton by hand. The components page (`/components`, over the mock journal alone, linked
from nowhere) draws each one live in its sizes and states, so a change to one is seen whole there and in its screenshot;
a primitive a page can show without data of its own adds itself there.

**A layout step inside the content pane is a container query, never a viewport breakpoint** (`@container` on the
pane's part or its `Panel`). The rail takes 13rem from the pane at `lg`, so a step keyed to the window is tightest
just past it. A step comes in once the pane has room for it and what it sits beside at full size, so nothing narrows as
the window widens. The wide screens' second column (Shape and space) stays the window's, at `2xl`, where the rail is
whole either side.

- **`ListRow`** (`src/components/rows.tsx`): a list's row, in a **`RowList`** that sets its kind's columns
  (`ROW_COLUMNS` in `src/lib/rows.ts`), which every row shares as a subgrid. **Columns fit their list**: each is as wide
  as its widest cell in that list, up to a most, rather than a width guessed from sample data, so a list of short ids
  leaves the room to its title, and the rows still line up whatever their cells hold. One free column takes the rest
  and cuts its text to fit; it never gets under 8rem, since it holds the row's name, which never vanishes, and a kind
  whose name needs more sets a floor of its own. Lists stacked in one panel share one grid. A cell never draws over the
  next column: what will not fit its column, an id with nowhere to break, is cut there by the row, so no cell has to
  remember to, and an id cut so is whole on hover. **A narrow list lets
  columns go**, in the order its kind gives them, so it fits its panel wherever the panel sits: a column shows from the
  narrowest container size with room for it, the columns that go after it, and those that never do. The `Panel` is the
  container, so a list goes by its own width, not the window's; every column shows at `@4xl`, which a list in a 1280px
  window reaches. What goes under the head line, a summary, its links, an earlier run, is a **`RowLine`** that spans
  from a named column to the row's end, never a hand-computed indent: no `pl-[…]` in `src/routes` or `src/components`.
  What sits under a row outside it, a tool call's body, is a **`RowGrid`** of the same kind with a `RowLine` in it. A
  new list is a new kind in `ROW_COLUMNS`, its columns written out there; an age column and a cost column are fixed,
  one width in every kind, so they line up from one list to the next.
- **`Fields`** and **`Field`** (`src/components/fields.tsx`): a detail page's field list, a label column in
  `panel-label` type and the values beside it, in prose or, with `mono`, in monospace data. The rows sit on their first
  baseline, so a label stays level with the first line of a value that wraps.
- **A document** is long-form prose set to be read rather than scanned: a guide page (`GuideText`) and a plan
  (`.plan-doc`). It takes its type from three utilities in `src/index.css` and nothing else, so the guide and a plan
  read alike: `document-text`, the body, `text-base` on a 1.75rem line, a step up from the app's `text-sm`;
  `document-section`, a `#` or `##` heading, the page title's `text-xl` semibold; and `document-subsection`, a `###` or
  `####`, the body's size in semibold. Two steps of heading, so a section stands a quarter above the body and a
  subsection apart from it by weight alone. A plan's size is the operator's (Settings): Normal is these, and the other
  sizes move the body and both headings together, the one place a size outside the steps appears. The guide stays at
  Normal. Code is set as everywhere else (`Code`, Rich text). A table is `document-table`, in a plan, the guide, and
  rich text alike: the measure's full width at least, wider where what it holds needs it, a hairline under its head
  and each row, no grid and no fill, its first column flush with the text, its head in `panel-label` as the app's own
  tables' are, its figures tabular, and a step under the text around it in `em`, so a plan's size moves it too. Code
  in a cell breaks where it must, keeping room for a dozen characters, and drops its chip; a table still too wide
  scrolls, its edges faded while there is more (`edge-fade`). Its measure is fixed, `max-w-3xl`. What lays a document
  out, the guide's rules between sections or a plan's margin, is its surface's own; its type is not.
- **`ReviewsTable`** and **`RunsTable`**: review runs and runs, one row each, on every page that lists them. On the
  page of what they belong to, the columns that would repeat it go, as a `ListRow` kind of their own. The reviews one
  request made of one commit, one per persona (DESIGN §31), are adjacent rows with no hairline between them, each with
  its own verdict, draft chip, cost, and age, and after the first, the free column says only `as skeptic`: rows, not a
  nested card, since the request is one entry read down its personas. A run's model, in its row as in its Run panel,
  takes no status color: a run the model asked for served none of reads `asked Y ≠ X`, asked first; until its session
  is read the row says `model unread`, muted, why in its tip.
- **`Empty`** (`src/components/panel.tsx`): what a list or page says when it has nothing to show, in muted text, in two
  sizes: `row`, as a panel's one row; `panel`, a page's main panel, centered with room around it. Its words are `no X
  yet` and one clause on why or what to do (`no runs yet: the overseer starts one when it is due`); `now` for what comes
  and goes rather than `yet`. A config key or a command in it is `Code`; a next step the UI can take itself is a link,
  or an inline button as Tick now is, never the CLI command that does the same. An error is never an `Empty`, and never
  a red sentence in a panel: it is a `Notice`, which names a refusal's guard and sets its `code` spans as code. A page
  whose read was refused (a 409) shows its `Notice` in its main panel.
- **`ListPanel`** (`src/components/list-panel.tsx`): a detail page's supporting list in its panel, headed by its noun,
  its `OrderToggle`, and its count. With no rows it is its header alone, counting `0`, with no `Empty` under it: the
  count already says it, and an empty list should not take a panel's worth of the page. A list the page's subject can
  never have is left out, not counted. The detail pages not yet built from it keep their `Empty` rows until they move
  to it, one rule for every page rather than one per page.
- **`None`** (`src/components/none.tsx`): what a field or a cell holds when it has no value, `none` in muted text in
  its place's own type, never a sentence of its own. With a reason, the reason follows a colon; in a column too narrow
  for it, the reason is on hover. One phrase per concept (`NO_TICKET` in `src/lib/words.ts`). A list with no rows is an
  `Empty`, not a `None`.
- **A model** (`src/lib/models.ts`) is named one way on every page: its id, `provider/model@variant`, in monospace,
  never `at high`. A dense list drops the provider, unless two of its models would then read alike, and gives the whole
  id in the tip; a picker, a field, or a table of models names it whole, as a gateway can serve its maker's models under
  the same name. No model is muted sans, never monospace, since it is no id: `runtime default` where nothing sets one,
  `unread` for a run whose session canopy has not read, and `None` with why for one read that named none. A model takes
  no status color, but one the runtime no longer lists, `status-failed`, since it refuses the next run.
- **`Input`**, **`Textarea`**, and **`SearchField`** (`src/components/input.tsx`): every text field, on
  `surface-raised` with a hairline and the accent's focus ring. An `Input` is one height everywhere, a form's, beside
  its default buttons. One holding what its form would not send is `aria-invalid`, which draws its border in
  `status-failed`, and says why on its own line under it, as soon as it is typed, never only on submit. A field to
  search or filter with is a `SearchField`: a magnifier, the field, what it says at its end (a count), and a ghost clear
  button while it holds text, in the place of what sits there empty. No page builds a field by hand.
- **`MarkdownField`** (`src/components/markdown-field.tsx`): a field the operator writes to an agent in, in the Markdown
  `RichText` draws and nothing more, from a `Toolbar` under the text and ⌘B and ⌘E, the rest typed, so what is written
  reads in the thread as it did in the field. It is one box, the text then the toolbar under a hairline, so Tab reaches
  the text first. An edit goes through the browser, so its undo takes it back. Its preview is a tab, live beside the
  text once the box is wide enough, or off. A field takes it when what it sends is later drawn by `RichText`, so the
  preview tells the truth; one drawn as plain text stays a `Textarea` until it is drawn so.
- **`PanelSkeleton`** (`src/components/panel.tsx`): what a panel shows while its data has not arrived at all,
  shimmering bars, each shorter than the last. It takes the minimum height its content will, so nothing moves when the
  data lands.
- **`PanelLoading`** (`src/components/panel.tsx`): a skeleton while a read is pending; a Notice once it has failed,
  saying why (`src/lib/read-failure.ts`: the server's words, or that canopy did not answer and `canopy loop` serves
  the page) and a ghost `Read again`. A 404 or a 409 is the page's own state, handled before it. The query client
  retries a read once, so a failure shows within about two seconds, and nothing refetches it after but the button or
  the stream. A page of many panels over one read shows it once, in its first panel.
- **`PanelFooter`** (`src/components/panel.tsx`): a panel's foot, the mirror of its `PanelHeader`: its actions under a
  hairline, default-size buttons in a line, then the line that says what they will do, then what one did (`Notice`).
  A `sticky` foot stays at the bottom of the page while its panel scrolls over it, opaque on `surface`; the page's
  scroll padding keeps what Tab moves to above it. A bar of actions never floats in a box of its own: it is its
  panel's foot. A config page's save bar is the one exception (below): it saves a whole page of panels, so it floats
  over them, and only once something changed.
- **A draft's card** (`DraftCardFrame`, `src/components/draft-card.tsx`): text canopy holds that would post as the
  operator on a PR, a thread's reply or a review's comment, is one card: `surface`, a `status-blocked/40` border while
  it waits on the operator, a header of its `panel-label` and what names it, its text, then its verbs in a row under
  it, `sm` buttons with the CLI's command on hover, `Edit` outline and `Drop` ghost. `Edit` opens a `Textarea` with its
  count against the bound, `Save` disabled past it, and `Cancel`.
- **A table of figures** (a chore's spend, the Spend page's) is as wide as its content and never wider than its panel,
  so a row's figures sit by what it names and the row reads in one glance; a column of text grows to its text, using the
  panel's room, and is cut only where the panel runs out, never stretched past its text. Its column heads are in
  `panel-label` type, its figures right-aligned readouts. A row head that names something is its name in medium weight,
  as `TicketTitle` sets a ticket's title, after its reference in its monospace link. Its panel's header repeats none of
  its rows. A report's table is a `ReportTable` (`src/components/report-table.tsx`, on `ui/table`), its columns each of
  a kind, which sets how its head and cells sit: the row's `name`, `free` text, cut only past the panel, a `figure`, a
  `bar` (`CellBar`), or a `word`; a table is not written by hand, so the rule holds in one place. Rows in groups stay
  one table, so their columns line up: a `tbody` per group, headed by a row whose `rowgroup` cell names it, with the
  group's own figures in its columns where it has them.
- **Readout tiles** (`ReadoutTiles`, `src/components/readout-tiles.tsx`) are a report window's headline figures: its
  sums, not a count of what is now, so they are not `Counter`s. Each is a `panel-label` name over a `readout text-xl`
  figure, what it counts in the name's tip, and, when the page has the window before's figure, a muted line under it
  saying how it moved, in `status-failed` only where the page says which way is better and it moved the other (a rising
  failure rate; never rising spend). A kind that spent nothing is no tile of a dash but a muted line under the grid, so
  the tiles hold what was spent. A figure still being read holds its place. A `Counter` stays a page's count of the
  present, with its state's color.
- **A bar in a cell** (`CellBar`, `src/components/cell-bar.tsx`) draws a column's figure as a share of its largest,
  where comparing the rows is the point: the figure in a cell of its own, which the table sizes to the column's widest
  so the bars start at one edge and no figure wraps, whatever the journal holds, then a rounded bar in the next cell,
  long enough that a narrow column's still compares, filled in `muted-foreground` or the series' own fill; never a
  state's color, but for a failure rate, in `status-failed`, a share of the whole rather than of the column's largest:
  it says what is broken. It is the eye's, `aria-hidden`. Where a table's rows sum to a whole, a bar is its row's share
  of the whole too, the percent on the cell's hover.
- **A sparkline** (`Sparkline`, `src/components/sparkline.tsx`) is a series drawn as a small `accent` line, where its
  trend is the point and a chart would be too much. Its scale is a chart's, 0 to `HEADROOM` over its largest; a point
  with no value breaks the line, and a lone one is a dot. It is `aria-hidden`: the words or the table beside it say
  what it draws.
- **Report cards** head the reports page: a card per page under Reports, in the nav's order, each a link to its page
  over 30 days, the longest window every page offers, with the page's name in `panel-label` type, its description line
  as the page gives it, and a sparkline of its by-day series where it has one. Each reads its own report, so one slow
  read holds its own line's place alone.

## Charts

What every chart follows (`src/lib/chart.ts`), so a new one needs no rules of its own; each chart's entry under
Patterns names what is its own.

- **Bars from zero**, in fill tokens of their own (Tokens), never a state's color. The plot's top is the peak and a
  quarter more (`HEADROOM`), so the tallest bar stops short of the edge, and the peak's value sits over its bar as a
  `readout`: the scale reads without hovering.
- **A bar's width is capped**, the row centered, so a sparse window draws narrow bars rather than slabs.
- **Stacked segments are 2px apart**, the surface between them, and any segment with a value is 2px tall at least, so a
  sliver still shows; the top segment's corners are rounded.
- **The axis** names its marks by one helper, `axisStep`: every mark of a short axis, every fifth of a long one, back
  from the last, so the latest is always named, and fewer where names that often would touch. A name is never cut to
  fit.
- **The legend**'s words are `muted-foreground` beside a swatch of the fill.
- **A value is on hover**, with its unit: `$1.50`, `30.2k sent`.
- **No data is `Empty`**, saying what there was none of: never an empty plot under a legend.
- **A table holds the same numbers** wherever the chart is `aria-hidden`, for a screen reader and for a value too small
  to see. Under a day chart it folds (`ChartTable`), closed on arrival, the table still in the page for a screen reader
  while it is. The legend says what each series counts, in its name's tip, so the table's heads are plain.

A measure over time (`TrendChart`, `src/lib/trend.ts`, the system resources page's graphs) is a line, not bars: the
accent, the area under it the accent's tint, from zero, broken where no reading was taken rather than bridged. Its top
is a capacity where the measure has one and the peak with `HEADROOM` where it has none. A threshold it is read against
is a muted line with its name at its right end, drawn only while it is under the top. The pointer snaps a crosshair to
the nearest reading, whose value and time stand in the latest's place. Beside the latest value it names the peak, or
the low for what runs out, such as free space; where the page says the latest beside the chart, it names only that
extreme. A threshold's line and name are drawn over the area, never under its tint. A measure under pressure draws its
line and area in its pressure's color, `status-blocked` or `status-failed`, the accent otherwise. Charts over the same
hour in one panel share one pointer, so pointing at any draws the crosshair on each, and the panel says the hour once,
with how long ago it was read, in `status-blocked` once a read again failed, rather than an axis under each. A measure
of the second rank, flat nearly always, is half as tall, in a row under the first. The plot is `aria-hidden`, and a
screen reader hears its latest value, peak, and low in words in place of a table.

The context chart differs where it must: its bars are its controls, each named for its call on hover and to a screen
reader, so no table repeats them.

## Patterns

- **Lists are rows in a panel** (`ListRow`), divided by hairlines, and every row reads in one order: its **state**,
  where it has one, so the left edge of a list answers "is anything wrong?" without a word read; its **own id**
  (`run:41`, `review:4`), in the same place on every page; **what it belongs to** (a ticket's key, a PR); the **chips**
  that describe it, each in a fixed column; then the **free column**, a title or what fills the rest; and after it
  **only readouts** (counts, cost, tokens, age), right-aligned, age last and cost just before it. A chip never follows
  the free column: there its place would shift with the title's length, far from what it describes. A list without a
  state leads with its id or its subject. On its subject's page a list keeps the order and leaves out what the page is.
- **Readouts** say an age, a moment, or a cost one way on every page (`src/components/age.tsx`, `timestamp.tsx`,
  `cost.tsx`). An age is `Age`, the CLI's largest whole unit with the local time in its tip, in the variant for what it
  measures: `ago` for a moment (`3m ago`), `span` for something that runs (`for 3m`, then `ended 3m ago`), and `bare`
  for how long an item has stood open, where its place says so (`3m`: an attention item, the rail's runs). The header's
  tick is the one exception: `3m ago` once it ended, so its line stays short. A moment shown whole is `Timestamp`, the
  local `Oct 8 10:30` with the ISO time the journal keeps on hover; a raw ISO string is never shown. Every time of day,
  hovered ones included, reads on the clock picked in Settings (`useClock`). A cost is `Cost`: `$0.42` as a readout,
  rounded to the cent as the CLI rounds, or a dash when nothing reported one, `none reported` on hover; never formatted
  in place, a hat's price included.
- **A fact on hover is a tip** (`Tip` in `src/components/tip.tsx`): a word's CLI spelling, an age's local time, a
  commit's whole hash, every one of a `+N more`. A `title` reaches neither the keyboard nor a touch screen, so a fact a
  list keeps out of its text is a `Tip`: it opens on hover, after half a second so a pointer crossing a list opens
  nothing, on the keyboard's focus, and on a tap; what it wraps becomes a stop for the keyboard. Text cut to fit is
  **`Clipped`**, the whole in its tip while it is cut and only then, so a title that fits is no stop. A tip is `text-xs`
  on `surface` with a hairline, no shadow and no motion, as a menu is, and the fact is in monospace where it is the
  CLI's spelling. Inside a link, a button, or an element with a `title` of its own, a tip is the plain `title` it was:
  a stop inside a control would be a control in a control. What the operator acts on is in the text, never only in a
  tip. What a report's column or figure counts is a tip too, on its name (`Hinted`), with a muted dotted underline
  saying there is one. A `title` that explains rather than informs, a button's hint, stays a `title`.
- **A link's page at a glance is a hover card** (`HoverCard`): more than a tip holds, a few rows of what the page it
  opens shows, as each header readout shows its page. It opens on hover after half a second, and on the keyboard's
  focus, and stays while the pointer moves onto it; a tap follows the link. Like a tip it is on `surface` with no
  motion. Nothing in it is found only there: it is a preview of the page, never a place to act.
- **A list in time can be flipped**, oldest first or newest first, from its panel's header (`OrderToggle`): a ghost
  button before the count, an up-down arrow and the order it is in, in words (`newest first`). A list sorted by each
  row's latest activity rather than by when it began says so (`recently updated`, after GitHub's sorts): its first row
  may be its oldest, so `newest` would mislead. Each list starts in the order the server sends it and keeps the
  operator's choice for that list alone, wherever it appears. It shows only when the list has two items or more. Search
  has none: its hits are each source's newest few, so flipped they would read as its oldest.
- **A list that grows without bound scrolls inside its panel** (`PanelScroll`) when other panels sit under it in the
  same column, past a height that keeps a week of rows whole, with a thin scrollbar, so the panels below stay in reach.
  The region takes focus, so the keyboard scrolls it too. A list that is its page's main content does not: the page
  scrolls instead. The attention list beside its item is the one exception (below).
- **A thread scrolls inside its panel too** (`ThreadScroll`): a ticket's conversation and a chore's notes. Past 60% of
  the window's height the messages scroll between the panel's header and the reply form, so a long thread never pushes
  the form a page away. It opens at its newest end, as a chat does, and keeps to it as messages arrive while the
  operator is within a bubble's gap of it; scrolled away to read, it stays where they put it.
- **The runs page is a row per subject** (`SubjectRunsTable`, `subjectRuns` in `src/lib/run-state.ts`): every agent
  canopy runs, a ticket's worker runs, a PR's reviews, and a chore's runs, in one list, so the operator sees where the
  sessions go and what waits on what. A subject's row is its latest run, which says where it stands, and under it
  `Show N earlier runs`, a `Disclosure` that opens the runs before it, each one line in the row's own columns. A ticket
  that asked, got its answer, and asked again is one blocked row, not two. The state filter goes by each subject's
  latest run, as do the rail's working runs: a blocked run a later one followed waits on nothing. Under the page's
  description, a line counts what runs against each `[capacity]` limit as the harness counts it, a full one in
  `status-blocked` with `full`. A ticket's page lists its runs flat (`RunsTable`), since every row there is the same
  ticket's.
- **A total cost** (`CostTotalRow`) is the last row of a ticket's Work panel and a PR's Pull request panel: the total
  as a `readout`, then, muted, what it counted (`over 3 runs and 1 review, 1 unpriced`), since the page lists only the
  recent ones.
- **The tickets list**: where the ticket stands (`TicketState`), the key, the phase, the `public` or `private` chip,
  the title in the free column, and the age. Where it stands is the running run or `waiting on you`, each with its
  run's dot, else `done` or `open` with the dot of a run that ended so, so every row has a dot and the column is never
  blank. Each kind's order of letting columns go is in `ROW_COLUMNS`; money and tokens go before what names a row, and
  where a ticket stands, which says when it waits on the operator, goes last. At half a monitor a run keeps its age
  and a slot its branch.
- **The tickets board** (`?view=board`, `TicketBoard`): the tickets list's tickets, under its filters and order, in a
  column per stage, every column shown, an empty one saying `none`. It only reads: no drag, since the loop moves a
  ticket. Past the panel's width the columns scroll sideways inside it, a focusable region.
- **The tasks list**: where the task stands (`TASK_LOOK` in `src/lib/tasks.ts`, a run state's dot and color), `task:N`,
  the repository, the text's first line in the free column, and the age; under the text, the first line of what its
  latest run said. The tasks waiting on the operator's reply come first, the rest newest first, so it has no
  `OrderToggle`. Above it, a `Submit a task` panel (`TaskSubmitForm`) on one line, as the reviews page's `Review a PR`
  is; on success a toast says what the CLI says and the form opens the task's page; the row arrives on the stream,
  never added by the page.
- **The epics list**: where the epic stands (`EPIC_LOOK` in `src/lib/epics.ts`, each standing a run state's dot and
  color by what it means: a proposed plan `waiting on you` in blocked's, one stuck without a plan in failed's),
  `epic:N`, its repositories, its goal's first line in the free column, how many of its breakdown's entries are filed,
  and the age, newest first. Above it, a `New epic` panel (`EpicSubmitForm`), the tasks page's form with the goal in a
  `MarkdownField` with its toolbar, since a goal runs to a paragraph: on success a toast says what the CLI says and the
  form opens the epic's page; with no stream event for epics, the page reads the list again.
- **An epic** (`/epics/$id`) leads with its breakdown, since what is left to file is what the page answers: the board
  (`EpicBoard`), at the page's width, a table with a row per entry in the plan's order and a column for each part of it,
  headed, so an id reads by its column; the members fulfilling it, each its run's dot, key, and phase, or `none yet`,
  muted. A narrow window wraps a row's cells and never stacks an entry into a card. Its mark says which plan it is read
  from, `proposed` in `status-blocked`, and opens that plan; with no plan it is one line, and a plan that does not read
  is a `Notice`. Under
  it, the members it has no row for. The members are the operator's to change there, as `canopy epic add` and
  `remove` change them: an approved entry's `none yet` offers Register a ticket, which opens its form in a row of its
  own under the entry, and the board's foot Add a ticket, for several entries or none; a member's Remove, a muted ghost
  shown on its line's hover or focus, asks under its row before it removes. Where a ticket is added, the form says
  that adding authorizes no work. Then the story (`EpicStory`, a task's story's bubbles) beside the requirements and
  contracts, and the plan runs. Pointing at an `R`, `C`, or `B` id anywhere on the page (`OutlineId`) lights it in the
  accent and the rows that cite it in the accent's tint, with no delay: fun that only adds, never dimming the rest, and
  whose facts each id's tip says in words. Its plan's text is on a page of its own, `/epics/$id/plan` (`EpicPlan`),
  which `Open plan` at the title's right opens, as a ticket's plan is: the newest plan in the editor, read only and with
  no margin, since an epic's plan takes no comments, then its earlier plans folded, newest first. A member's own page
  says whose it is, so its record reads as one story: its Work panel's `member of` field (`MembershipField`), the epic
  and its entries, or `of no entry`; its plan page, under the description, the epic plan its planner read, by hash, and
  when that was approved (`FollowedEpicPlanLine`), and a newer approval since as a fact, never as a warning. An epic
  has no identity panel, so its stop (`EpicActions`) sits at the title's right after `Open plan`, `sm` buttons as that
  one is, asking once more inline as a task's does and saying that its members' work is left as it is, with what it did
  under the buttons. A stopped epic says so, and when, in its description and under its goal in its row, and its plan
  page offers Approve alone, since it takes no reply.
- **A task** (`/tasks/$id`) is one story: its title `task:N` and its text's first line, its description where it
  stands, then the detail skeleton, with the story as its thread: a Conversation panel (`TaskStory`) whose oldest end
  is the operator's instruction, whole, as their own bubble, then its messages, each naming its run as `task:4#5`, which
  opens the run's page. The panel's foot is its answer, as a ticket's is: the `ReplyForm`, then its stop under a
  hairline. Stop asks once more, since a task has no start to undo it. Its main content is the Report panel, its newest
  run's report that left one, laid out read only through the plan's schema (`PlanDocument`), so it reads as a document
  and stays text. Then What it left (`TaskLeft`): its repository, branch, pushed commits, draft PR, and the tickets
  filed, a `None` with its reason for what it left nothing of, and one muted line saying all of it is throwaway until
  given a pass.
- **The tickets filters** narrow the list two ways at once (`src/lib/ticket-filter.ts`). Where a ticket stands is
  chips in the panel's header (`?show=`): `open`, `working`, `waiting on you`, `blocked` (the overseer's phase for a
  ticket an open blocker holds up, LOOP §7; no dot, since no run of it asked anything), and `done`. Under the header, a
  search field (`?q=`) keeps the tickets whose key or title holds every word, narrowing as they type, each keystroke
  replacing the history entry, so Back leaves the page. A filtered count says `6 of 41`, and an empty result says which
  filter left nothing. Both filter the list the server sends, not the whole journal.
- **The PR and review filters** narrow the pull requests and reviews lists the same way (`PullRequestFilterBar`): a
  search field over the PR, repository, and ticket, and a repository picker (`RepoFilter`) of the repositories the
  list's rows are in, shown while there is more than one. The reviews list adds a picker of one of its PRs' authors
  (`ChoiceFilter`, `?author=`), shown on the same terms.
- **Chips** (`Chip`) label a row with a fixed word: a kind, `private`, a reason. Never with journal text. A word the
  journal stores goes in as `word` and reads as words: underscores become spaces (`worker failed`), while the CLI's
  spelling stays in its tip, so it can still be found in `attention.md` or typed into the CLI (`src/lib/words.ts`). A
  reason's or a phase's tip says under the spelling what it means, in a line (`src/lib/meanings.ts`). Outside a chip, a
  phase or a status reads the same way (`Word`); no journal word shows with its underscores. Journal text that is not a
  fixed word and a count are muted monospace, never a chip. A chip with a long word in a narrow column cuts it to fit,
  the whole word in its tip; none is stretched to its column. Its color is its `tone`, from the one map of them (`Chip`
  in `src/components/status.tsx`): its color's hairline over the same color's tint, so it holds its edge on a selected
  row; `plain` in `muted-foreground`, else the status color of the state it marks, or a proposal's own hue. No chip is
  colored by classes of its own.
- **A status on a detail page** is its description's first word alone; the identity panel's header names the panel
  and nothing else, so the state is said once. A run's journal says `done` where a tick's and a chore run's say `ok`:
  each is the CLI's word for its own, kept as it prints it, and in a list's row both wear `status-done`.
- **A run state named in words** (a filter's chip, an empty filter's message, a question's chip, the rail) is the
  operator's: `blocked`, a run that asked, reads `waiting on you` (`RUN_WORD` in `src/lib/run-state.ts`) wherever it
  shows. The URL keeps `?state=blocked`, and a run's own status in its page's header stays the CLI's word.
- **A ticket's title** (`TicketTitle`) follows its key, in medium weight, so it reads as the row's name and apart from
  what a run said under it; one line, cut to fit, the whole in its tip while it is cut. A ticket with none yet reads
  `untitled`, muted, so its cell is never blank, never the run's kind in its place. A ticket's page heading sets the key
  in muted mono before it.
- **Counters** (`Counter`, `src/components/counter.tsx`) head the worktrees page. Each is a label, the value, and at
  most one line under it, with a top rule in the state color it counts, washing down from the rule. A line is state,
  never what every visit would say, nor what another counter or the nav already says (One home per fact); a counter
  with no line of its own shows none. A counter counts what its line lists, and a line that splits the count names only
  the parts there are, never a `0 broken` among them. The attention page has none: the nav's badge, the rail, the tab's
  title, and its icon carry the glance, and tiles there only said their numbers again.
- **The process tree** (the system resources page, `ProcessTree`) answers "is it canopy?" first: the loop's tree,
  its parents named in one muted line over it, each run's process carrying its run as a link in the accent, its
  reference and what it works on (`run:41 ABC-101`), and what the run and everything under it add up to, open or
  folded; then what else is busy under an `elsewhere` heading, a run of idle parents on the way to one child drawn as
  one muted line of their names. A figure sits over a thin bar of the accent's tint, the processors against one core
  and the memory against all there is, for the eye alone. The **cpu** and **memory** heads are its order: a head is a
  button, the column it orders in the foreground with a down arrow, `aria-sort` on its cell. **All**, the order, and
  the folds are kept in this browser, so the page is as the operator left it.
- **The spend chart** (the spend page) follows Charts: a bar per UTC day, the series stacked bottom up in `SERIES`
  order. Idle overseer spend sits on the baseline under the rest of the overseer's, a lighter shade of its hue, so the
  two read as one. A day with no cost is a 1px `border` stub on the baseline, so it reads as nothing spent, not a column
  gone missing. Each series has one name, in the totals, the legend, the table, and a bar's hover, with what it counts
  on the name's hover: `overseer` is the live overseer's whole spend, idle ticks' included, as `canopy spend` counts
  it, and `idle ticks` the part of it idle ticks made. The page's description is the window's state (`spendLine`). The
  chart is `aria-hidden`: the table folded under it holds the same numbers. The window is a segmented control
  (`WindowToggle`) in the page header's controls, as on every report, kept in `?days=`; `by week` draws a bar per
  local ISO week, named by its Monday. A window where no run reported a cost is one `Empty` line in place of the chart,
  its legend, and its table. By model's ids link the runs page's runs on the model.
- **The failures chart** (the health page), **the red checks chart** and **the green-first chart** (the CI page),
  **the first reviews chart** (the Reviews page), **the month chart** (the reports page), and **the answers by week
  chart** (the checklist page) are the spend chart's `DayChart`, each stacked in its own fills (Tokens), with the
  legend and a table of the same numbers under it, and its window the same segmented control. A window where nothing
  happened is one `Empty` line. The month chart's picked month is marked in the accent's tint, a click on a bar picks
  its month, and the table links each month for the keyboard; with no span picked the page fits the journal.
- **The Reviews page's panels** each hold one thing: a chart is alone in its panel, and a table that answers a
  different question from the one beside it gets its own panel.
- **The answer bar** (the checklist page's By item) is an item's answers as one rounded bar, each answer its share of
  the runs reminded in its answer fill, in `canopy checklist`'s order. Every bar is the same length, since the share is
  the point, not the count; the counts stay in the row's columns, and in words in the bar's tip and for a screen reader.
  A held or fixed count opens a `Popover` of the runs behind it, on a mouse's hover after half a second as a tip does,
  staying while the pointer moves onto it, and on a click, a tap, or the keyboard, which keep it until a click outside
  or Escape. A hover leaves the focus where it was.
- **A table of PRs** (`PullRequestTable`, `src/components/pull-request-table.tsx`) is a report's per-PR table: the PR
  with its unit's phase, its ticket, then the page's own figures.
- **The first-call chart** (the spend page's First calls by week) follows Charts but where a rate needs otherwise: a
  bar per local ISO week of one kind's series, as tall as the share of the week's first calls the cache served, its top
  the whole, so the axis means the same in every window, and every bar's rate over it, since there are few and the eye
  compares neighbours. A week whose runs used a runtime version or definitions snapshot no earlier week's did has a
  rule down the gap before its bar, and a line under the chart names what it used, in `canopy spend`'s words, so a
  screen reader hears it beside the table. The kind filter has no `all`, since kinds' prefixes do not sum.
- **A slot strip** in a pool's header: one small square per slot, in slot order, in the worktree state's color, an idle
  one hollow. The counts beside it say the same in words, so the strip is `aria-hidden`.
- **A slot is one line** in our state words, never treehouse's (its word is in its tip). An idle slot shows its state
  and number alone, muted. A dirty slot's note, in `status-blocked`, says what it blocks and what clears it, since it
  is the slot most likely to sit there unnoticed. The branch and the processes treehouse found share the free column,
  each cut to fit with the whole in its tip. A pool treehouse could not read says why as a `Notice`.
- **Idle slots fold**: three or more in a row are one line, their state and then `Show 37 slots, #4 to #40`, a
  `Disclosure` that opens each slot's own line under it, since a pool of many slots is mostly idle ones, which say
  nothing but their number; folded, those with work in them stay in reach. One or two in a row show as they are, since
  a toggle would save no room.
- **The worktrees filter** is the runs page's, by worktree state, in the Pools panel's header before Read again: it
  keeps the slots in that state and the pools with one, under `broken` the pools treehouse could not read too. A pool's
  header still counts all its slots. The page's description is the pools' state, with how fresh its read is, since it
  is read on a timer.
- **The attention list is an inbox**: one list, most severe first, beside the selected item while the page is at
  least 48rem wide (`@3xl`). There the two scroll apart: the list is `sticky`, as tall as the window has room for, and
  scrolls in itself, so the page scrolls only the item, however tall. Choosing a row takes the page to its top, so the
  item opens at its head and the row stays where it was clicked; an item the URL names whose row is out of view brings
  it into view in the list, which alone moves. Narrower, the list and the item take turns, each the page's whole width:
  the list shows until an item is chosen, which opens in its place with `Back to the list` as its first stop, where the
  focus goes, since the row went with the list. A reply that answers its item moves on to the next item that waits on
  the operator's answer (`nextWaiting`), its row focused, and a toast says what the reply did, since the form that said
  it goes with its item; with nothing else waiting the item stays. Severity (`src/lib/attention.ts`): broken work
  first, then what waits on the operator's answer, then every other reason, then chores' findings; within each, the
  item open longest first. Settings can hide the findings, in this browser alone: the list, its count, and the nav's
  badge leave them out, and a muted line above the list counts what it hid, so a hidden finding never reads as none.
  A row reads as an inbox's: its reason, subject, and age, then its ticket's title or its task's first line as the
  subject, then its detail, muted, as the preview. A plan waiting on the operator says after its subject how many
  decisions it leaves open (`DecisionsCount`), in `status-blocked` as a counter of what waits on them, so a plan that
  asks something is told from one that only wants approving before either is opened. A reason chip takes `status-failed`
  or `status-blocked` for the first two severities, plain otherwise. An item's detail is the harness's line, with its
  `code` spans set as code and
  nothing else read (`InlineCode`), but for a PR's address, which is a `PullRequestLink`, and a run named as
  `canopy show` reads one, which is a `RunLink`; the CLI's `answer with canopy reply KEY` is left off a question's
  detail, since the page's reply form is the answer. The list's panel header holds its count, after the longest wait
  when one stands. The selection is `?item=<id>`; with none, the most severe item about a ticket. When the selected
  item leaves, the row that took its place is selected, so a long list is worked down where the operator stands rather
  than sent back to its top.
- **An empty attention list tells never started from all handled** (`EmptyAttention`). Before the journal holds any
  ticket, the page is the first step, an `Empty` saying how to get one, with Tickets a link and Tick now the header's
  button inline, since an inbox that was never filled is not one emptied. Once there was work, the empty inbox (Fun) is
  the reward, and a digest for a tab left open all day: one centered column at reading width, muted type, no panel, no
  tiles. `Nothing needs you.`, then the day's PRs opened and runs ended, then the working count and the latest tick.
  Every figure must hold on a reload, so its window is the local day, which the journal answers; items cleared are not
  counted, since only a tab sees one go. A figure of none is left out. The tick repeats the header by the operator's
  choice, an exception to One home per fact. A paused loop says so, in `status-blocked`, since a quiet page and a loop
  told to wait look alike. A loop down drops the digest whole: none of it stands while the loop isn't answering.
- **The attention detail: the reason picks the first block**, under the item's head, what the reason asks of the
  operator (`ask` in `src/lib/attention.ts`), so the action it calls for is never buried under louder controls about
  something else. A run that broke: the ticket's latest run as a `RunsTable` row, then the grant when it is stuck at a
  limit, so why it failed is read and another try allowed without leaving the page. A PR that waits on someone else:
  the PR's `LinkOutButton`, so the PR is one tab stop. A wait on the operator's answer: the reply form is the action,
  and a question's head names it, `Waits on your answer to message 5, asked 3m ago`, rather than saying it, since the
  conversation holds it. A plan: its card, with its open decisions, `Approve`, and `Open plan`; a feedback plan's, a
  line naming it and an outline link to the PR's page, where it is approved. A running run's question: the question as
  the run's page draws it, each option a button that answers by letter; a toast says what the answer did, since the item
  leaves with it.
  Memory's items: the proposals or lessons they name, with their verbs. Drafts a run left: an outline link to where
  they sit. A task's: `task:N` and its text's first line, then an outline link to the task's page, which holds its
  question and its answer, never the `canopy` commands its detail names. An epic's plan: `epic:N` and its goal's first
  line, then an outline link to its plan's page, where it is read and approved, and how many decisions it leaves open,
  since that page is where they are answered. A ticket's run refused its model: the
  ticket's models, the runtime's list read fresh as the item opens, so the model it no longer lists is marked already.
  An item about nothing the page shows whose detail names a `canopy` command: the command, `Copyable`, and nothing to
  answer. A ticket's item then shows its answer (below), with the ticket's own verbs and any other limit as a quiet
  row under the reply; on a reason that is not about the ticket's thread the verbs and the limit lead, under the head,
  as what it asks.
  A chore's item shows the chore's notes and the note form, and a finding a ghost `dismiss` beside its age and, in
  place of its detail, the finding as its chore's page has it. The page keeps no list of the runs working now: the
  rail's, on every page, is the one, so one count of them shows at a time.
- **The answer** (`TicketAnswer`, `src/components/ticket-answer.tsx`) is where a ticket is answered, one component on
  its page and on its attention item: its conversation, the reply form right under it, then the ticket's verbs and any
  limit it is stuck at (`TicketVerbs`), each under a hairline. So the reply is the first stop the keyboard reaches after
  the conversation, and Stop, Forget, or Allow one more never stands between them. On an attention item its header
  wears the ticket's `private` or `public` chip and its phase, which the page says by its title and in its Work panel.
  When one of the ticket's attention items clears while its page shows it, a leaf drifts off the conversation's header,
  as a cleared row drops one in the list (Fun): the reward is for the item clearing, wherever it was answered.
- **The reply form is always open** (`ReplyForm`), on every ticket and every chore, never folded under a `Disclosure`: a
  note for the next worker is as likely as an answer to a question, and a click to reach the box hides where the
  operator writes. Its label names the message it answers while a question waits, and the form then wears the open
  question's tint and hairline, so the question and the box answering it read as a pair. Focused, the box takes the
  accent's tint, the operator's side. Its count of characters shows only past 80% of the bound. On a public ticket it
  says what a reply is for and where it goes: for its next worker, as an instruction, never on the ticket. While a
  worker or planner runs on the ticket, and no question waits, a checkbox beside the button, `Tell run:41 now`, sends
  the reply to that run instead (DESIGN §44): unchecked by default and after each send, never kept, since steering an
  agent mid-edit is a choice, and the placeholder says what checked does. A ticket's page description is its state,
  not what public or private means (`ticketDescription`).
- **A conversation** is a column of messages, each a head line over a bubble. The head leads with who, in sans
  `font-medium` `foreground`, then what (kind, run, what it answers, how) and its chips in muted mono; its id and age
  are a readout at the end away from the bubble's square corner. A message that carries on the one before it (the same
  speaker, kind, run, and channel, within five minutes, answering nothing) keeps only its chips and readout, and sits
  closer under it. A bubble is as wide as its words, up to 42rem and never past 85% of the panel, so the other side
  keeps a gutter at any width: `surface-raised` for a worker's report or a question answered, a hairline on `surface`
  for a tracker comment, quoted since it is data from outside the loop, the `status-blocked` tint for the question
  still open, the one amber bubble, which carries a `waiting on you` chip, a dashed hairline with muted text for
  canopy's note on what a tick did, and the accent's tint for the operator's own words, which sit on the right, their
  head line mirrored. A bubble's corner nearest its side is square. A forgotten ticket's conversation shows what came
  after the latest forget; each forget heads the attempt it ended, its messages folded under a `Disclosure` and dimmed,
  since the loop no longer reads them. Bodies are rich text (below): always text, but for their URLs. An operator
  message no `ok` tick has read carries a `waiting for the next tick` chip in `status-running`, and a `seen` chip with
  a check, in the accent, once one has, so a reply never goes unacknowledged. One sent to a running run says `to run:41`
  in its head and wears that run's chips in their place, in `canopy show`'s words: `not fetched yet` in
  `status-running`, `heard` with a check, in the accent, `never fetched` muted once the run ended, and `next run reads
  it` muted when canopy could not write it where the agent reads it; an item it answered carries an `answered`
  chip, with a line saying it leaves at the next tick. While a run works the ticket, the conversation ends on it, on
  the worker's side, as a chat shows someone typing (`WorkingNow`): a pulsing `RunDot`, `working now`, its run, its
  kind, its latest tool call, its cost so far, and for how long, from the runs on the stream, so it rises in when the
  run starts and leaves when it ends.
- **A running run's latest tool call** (`RunDoing`, `src/components/run-doing.tsx`): one line of mono data, the tool
  in `status-running`, what the call did muted (a shell call's command, else the runtime's title; cut to fit, whole on
  hover), and how long ago. A running run's row has it where an ended run's summary goes, `WorkingNow` after the kind,
  and the run's page as its `last call` field. It is agent output, rendered as text.
- **A running agent's progress** (`RunProgress`, `src/components/run-progress.tsx`, DESIGN §41): the agent's own
  account of where its work stands, which the operator reads to know what a run is up to now, so it leads wherever it
  shows. Whole, it is the summary in `font-medium`, a meter of its steps if it has any (a segment each on the bare
  `border` track: only done fills its segment, in `status-done`; working fills half in `status-running`, striped and
  sweeping while the run runs; blocked or stuck half in `muted-foreground`) with `N of M done · stage S`, its question,
  then its work as one checklist, each entry led by a mark for its state. Its question is a box on the
  `status-blocked` tint while it waits, muted once answered or ended: `asks you`, the question, and each option a
  full-width row that answers with its letter on a click, `recommended · working toward it` after the one the agent
  works toward. Amber means that question alone: a stale update is a clock and `stale` in `foreground`, a fact about
  the record, never a request. A run's and a review's page lead with it as a `Progress` panel (`Last progress` once
  ended), a ticket's `WorkingNow` shows it as a bubble on the worker's side, a running run's row as one line, and the
  rail's working row of a worker run as its meter under the phase line. Agent text, as text.
- **A URL in journal text** (`LinkedText`): an http or https URL in a message body, a summary, a rationale, or a detail
  is a link in `accent`, underlined so it reads as one inside prose, its text the URL as written; it opens in a new
  tab. A PR shown in its own place is a `PullRequestLink` (below), and so is a GitHub PR's address in a bubble or a
  finding, as in the harness's lines (`InlineCode`).
- **A chore's notes** are a conversation of the operator's words alone, after the chore's findings and runs and before
  its spend, with the note form open under them (`ChoreNotes`). A note no run of the chore has started since carries
  `waiting for the next run` in `status-running`: no tick reads a note, so the tick chip would be wrong there.
- **Decisions** are rows (`Decisions`): the subject, a ticket or chore as a link, a unit as its ticket and repository
  (on its subject's page, the tick instead, with its age), the action as a chip, a PR as a link, and the rationale
  under them as rich text. A `refused:` action's chip is in `status-failed` and an `attention:` one's in
  `status-blocked` (`src/lib/decisions.ts`); the rest are plain. A tick in a list is its status, a dot and its word in
  the header's tick colors (`src/lib/ticks.ts`), then its id as a link, a `dry run` chip, how many decisions, its cost,
  tokens, and peak context, and when it ended; its summary under, from its id.
- **A transcript** (`TranscriptPanel`) is a session's events as rows, in the order the runtime printed them, each with
  its time from the session's first event. The agent's text keeps its line breaks, its reasoning muted and italic
  under a `thinking` label, folded past four lines as rich text folds. A tool call is a native `<details>` whose line
  says what it did and how it ended (`src/lib/transcript.ts`): a `RunDot` in `done` or `failed`, the tool's name, and in
  monospace a shell call's command after the directory it ran in, muted: on a run's page named from its repository
  inside the run's worktrees (`web $`, `web/src $`), whole in `status-blocked` outside them, so a call that wandered
  off stands out; the line whole on hover. Else the runtime's title, else its input's short values; under that, muted,
  its error's first line in `status-failed` or an output of one short line; then how long it took. A canopy command that
  printed a refusal is `failed`, with a `refused: <guard>` chip. It opens to its input and its output, JSON colored as
  a tick's output is, every value as written. A model call is a muted line with its number, its tokens `in · out`, and
  its cost, opening to its tokens by kind and the input and output sections By call shows, built only when opened. A
  runtime error is tinted `status-failed`. The header has the session id, then a hairline rule and the modes: the
  order, By call, and All open, a `Toggle` that opens every call. Above the rows, how many tool calls, failed and
  refused ones, and model calls, and at that line's end a search field (`Find lines`), which keeps only the rows with
  a line that holds it, every character taken literally, says how many that is, and marks its matches on the accent's
  tint as the search page's are; a tool call whose input or output holds it opens to it, and a search nothing matches
  says so in place of the rows. By call groups the rows by the model call they came from, once the counts name two:
  each call a `Collapsible` row, its number, what it did, an `unfinished` chip when the session ended first, its
  tokens, and its cost, opening to an input section (the first call's the prompt canopy kept, a later call's each tool
  its predecessor called) and an output section, the call's rows as above. A run or chore run that ended `failed`,
  `crashed`, or `unknown` has an `ended on` field after its summary (`EndedOnField`): the transcript's last runtime
  error, else its last failed or refused tool call, a button that shows its row. A transcript with no events is its
  header alone, the session and then why in a few words as its readout (`log gone`, `no session`, `no events yet`).
  A transcript over 1,000 rows draws the first 1,000 (`TRANSCRIPT_BUDGET`), since one at the server's bounds drawn
  whole is 80,000 elements, in a `PanelScroll` of most of the window's height, so the panels after it stay in reach;
  after them a fold, a row with a ghost `xs` button in a diff's fold's words (below), draws the next 1,000, and only
  adds. A search still reads every entry, drawn or not. The search redraws the rows in a transition behind the field
  (`inPage`), so a key typed never waits on them. A row shown from the chart or `ended on` is drawn first, with every
  row before it.
- **A transcript's context** (`ContextChart`, `contextShape` in `src/lib/transcript.ts`) sits between the counts and
  the rows once a model call has its tokens. Its line, in the counts' band: a `context` label, the peak, the largest
  single addition as a button in the accent with its tokens and the call it grew, and at its end `Show chart`, a
  `Disclosure`. The chart is closed until opened, since a transcript is opened to read what the agent did far more
  often than to ask why its context grew; each kind of page keeps it open or closed across reloads. Open, a bar per
  call, as tall as what it was sent, from one baseline: what the call carried from the call before in
  `context-carried`, what it added on top in `context-added`. The bars are a `ToggleGroup`'s items, each named for
  its call, size, and step on hover and to a screen reader. The call picked, at first the one the largest addition
  grew, sits raised, and a line under the chart says what grew it: the step on the call before, then what that call
  printed, largest first, each its share of the step by its characters, at most five and then how many more; the first
  call's line splits it into the prompt and the runtime's own. Each entry named is a button that shows its row, open or
  closed: it turns By call and the search off, scrolls the row to the window's middle, focuses it, and sets it on the
  accent's tint. A session with fewer than two calls the runtime counted tokens for has the line alone, with no chart:
  one bar says nothing the line does not.
- **A tick's output** (`TickOutputPanel`, `src/components/raw-output.tsx`) is the overseer's file as written, under the
  tick's transcript, and **a run's output** (`RunOutputPanel`) its log the same way: one muted line naming the file
  until `Show output`, a `Disclosure` in the header, opens it. A tick that kept no file has no Output panel: its
  transcript says why. Open, it is one monospace block, its lines wrapped anywhere, scrolling inside the panel and
  opened at its end, where stderr is; the file's size is in the header, and a cut says so above the block. A line that
  parses as a JSON object or array is colored as written, never reformatted (`src/lib/json-lines.ts`): keys, strings,
  numbers, and literals in the `syntax-*` tokens, punctuation muted; any other line stays plain. A Pretty `Toggle` in
  the header lays each JSON line out over several, by the space between its tokens alone, so every value stays as
  written. Each tick's panel keeps its own choice across reloads, as a list keeps its order.
- **Rich text** (`RichText`, `src/lib/rich-text.ts`) lays out what an agent wrote, a summary, a rationale, and a
  conversation's message: line breaks kept, `-` and `1.` lists, headings as a `font-semibold` line, `#` and `##` a step
  over `###` (`text-base`, a small step, as the page's heading ladder does not apply inside a bubble), `>` quotes as
  their own blocks, a `---` rule as a hairline, a pipe table as a document's (`document-table`, A document) with its
  columns aligned by their colons, fenced code as a
  `surface-raised` block, colored as the guide's is in the language its fence names (`CodeBlock`), and `code`,
  **strong**, *emphasis*, and ~~struck~~ inline. Code, inline or fenced, is `text-code`: a step under its line on a sans
  palette, where the change of face sets it apart, and the line's own size on a mono one, where a smaller copy of the
  same face reads as a mistake. Inline code sits on `code-chip`, a tint of its own ink, so it stands apart on any bubble
  or tint without a tile darker than the text around it. Every code span in a sentence is drawn so, through `Code`
  (`src/components/code.tsx`), so one span never flips look beside another; a key or path shown as data on its own line
  stays plain mono. It reads nothing else: other markup, a labelled link's included, stays characters. Every piece is
  React text, and every piece but code goes through `LinkedText`, so a URL outside code is a link to itself. In a
  list's row it shows the first four lines and a `show N more lines` toggle in the accent; text one line over shows
  whole.
- **The guide** (`/guide/PAGE`, `src/lib/guide.ts`, `GuideText`) is the operator's documentation, a page each, as
  Markdown in `src/guide/` (docs/design/CONVERSATIONS.md §22), laid out as a documentation site rather than in panels:
  on the left, the pages by group (`SOURCES`), the page shown in the accent, once the pane holds it and the article's
  whole measure, else folded into a `Guide pages` toggle above the page; in the middle, the article at `max-w-3xl`, in
  a document's type (Primitives), each `##` a section under a hairline and each heading a link to itself on hover, and
  at its foot Previous and Next; on the right, once the pane holds that too, `On this page`. So the article never
  narrows as the window widens: a column comes in only where the article keeps its measure. It reads what rich text
  reads, headings as real headings with their anchors as ids, and labelled links in the accent: to a guide page, a
  heading, a section of the UI, or the web in a new tab. A link to anything else stays characters, and `guide.test.ts`
  fails on it. A page opens with `# Title` and then a lead, says what the operator sees and does in the UI's own words
  (`waiting on you`, not `blocked`), and leaves how the code does it to the code and why to the design, in the voice
  `AGENTS.md` sets. An empty fence that names one of the repository's example files after its language (`EMBEDS`)
  shows that file whole, as it is when the guide is built, so a page never keeps a copy of one. A code block is colored
  as a diff's code is (A review), in the language its fence names, plain until its grammar has loaded, and copied from
  its corner. A ```` ```mermaid ```` fence is drawn as its diagram, as a plan's is (D131), in a panel of its own whose
  head is its `accTitle`, which names it, with its actions in its corner, and `guide.test.ts` fails on one mermaid
  cannot read or with no `accTitle`. A diagram is for a shape the prose would take paragraphs to hold, beside the
  prose, never instead of it. A new page is a file there and a line in its group in `SOURCES`.
- **A question before losing work** (`AlertDialog`): a page that holds the operator's work not yet saved or sent asks
  before it is left, in a dialog centred over the canvas: its question as the title (`Leave this page?`), what leaving
  loses under it, then an outline `Stay`, which takes the focus and which Escape gives, and `Leave` in `destructive`. A
  form says it holds words not yet sent with `usePending` (`src/hooks/use-pending.ts`); a move within the page never
  asks. Closing the tab asks too, in the browser's own words. A question about one item, such as deleting a comment,
  asks in that item's place instead.
- **A plan in its editor** (`PlanEditor`, `src/components/plan-editor.tsx`; docs/design/PLANNING.md §25): the plan in a
  `Plan` panel, and the comments in a `Comments` panel beside it once the page gives both room (a container query, so
  the rail's width counts), and under it, as a list, below that. The plan's panel stops at its text's measure, so on a
  wide page the comments stay against the text. Beside the plan, the comments are its margin, as a shared document's
  are (`src/lib/plan-margin.ts`): their panel drops its border and surface, each open comment is a card of its own at
  the height of its passage, in the plan's order, one that would overlap the card before it moved down to clear it, and
  the open one, or the comment being written, sits exactly at its passage, the cards before it moving up to make room,
  so opening one never scrolls the page away from what it is on. The plan is laid out as a document (`.plan-doc`), in a
  document's type (A document, under Primitives). What the plan holds as characters (HTML, an image) is muted monospace;
  a link is underlined in `muted-foreground` with its address on hover, never a link. A Mermaid code block is drawn as
  its diagram (`src/lib/plan-diagram.ts`), a section of the plan's panel rather than a card in it: a hairline, a head
  in `panel-label` naming it, by its `accTitle` or else its kind, with `Source` at its right as a panel head's control
  is, and the picture at the text's edge. It is drawn in the app's data dialect, Plex Mono at 13px and spaced densely,
  the face carried inside the image since an image can use no other, and drawn again when the theme or palette changes,
  as wide as it is drawn or narrower to fit, but never under three quarters of that, past which its labels go unread:
  a wider one scrolls, each edge faded while there is more past it (`diagram-image`, `edge-fade`), as the guide's do.
  Every kind is drawn in one hand (`themeCss` in `src/lib/diagram.ts`): one label size, one corner, one line weight, a
  subgraph dashed, a sequence's actors once, at its top, and its captions lifted off the lifelines they cross. Its
  actions sit in its head before `Source` (A block's actions, below). Its code shows, under the picture, while `Source`
  is on, while the cursor is in it, or while a comment or a change is marked in it, and out of sight it is clipped, not
  removed, so a screen reader still reads it; one that
  cannot be drawn shows its code and why. The toolbar (`Toolbar`, below) is `icon-xs` toggles in groups split by
  hairlines, then `Comment`, enabled while text is selected; each control's tooltip names it and the shortcut the editor
  binds to it, on this keyboard, and declares the same keys as `aria-keyshortcuts`. The paragraph's style and the
  table's actions are menus, as a document's are, and an action leaves the cursor in the plan. The plan's header says
  where the plan stands, at its right: its chip and its age, then its modes, as a transcript's are: `Changes since plan
  1`, a `Toggle` that marks what changed since the plan this one replaces (words added on `diff-add`, removed struck
  through on `diff-del`, where they were; a block added whole as one, with a bar at its left, so a new section reads
  as one change, not as a pill for each run its marks break it into; a section moved, a `moved` label; a section
  removed, one `<details>` line where it was, so a dropped section is one change, not a wall), pressed as a waiting
  plan opens, since that is when it is read for what changed, with how many changes it marks and buttons that step the
  cursor through them; `Markdown`, a `Toggle` that swaps the document for its Markdown in a plain monospace field,
  editable where the plan is, the changes, the outline, and the toolbar stepping aside; and `Outline ▾`
  (`src/lib/plan-outline.ts`), the plan's headings, the section scrolled to in the accent, each `##` section's row on a
  ticket's newest plan ending in `read` and `a concern` marks, this browser's alone (`src/lib/plan-marks.ts`), never
  the journal, which hold while the section's words are as marked, so a rewritten section is unread again; then a menu
  that copies or saves the plan's Markdown whole, as the page shows it (`PlanFileMenu`), named as `canopy archive`
  names the plan, the same menu a task's report and a feedback plan's file carry. Its file's path closes the page's
  description, on a line of its own, with a copy button. A page's plan prints alone, as a document, under a line naming
  its ticket, plan, status, and date, in the light theme whatever the screen shows (`src/lib/plan-print.ts`): no
  shell, header, toolbar, foot, decisions, or comments, a diagram and a table each kept to a page where they fit, a
  table and a code block wrapped, and a diagram's picture still drawn dark turned round (`invert` with its hues
  kept). While the changes are marked, a commented passage drops its
  tint, so no word wears a comment's and a change's at once, but keeps an underline in the accent. The header is
  `sticky`, and what the editor scrolls into view stops below it. A commented
  passage sits on the accent's tint; the open one, or the one being commented on, darker and underlined; the cursor in
  a passage opens its thread, and so does a click on its card, or Tab into it, which leaves the plan where it is;
  the cursor leaving it, or Escape, closes it. A thread is its passage quoted, the comment and its replies as text with
  their ages, and its actions, in words, ghost `xs` buttons in muted text, never an icon alone: `resolve` (`reopen`)
  and `delete` at the right of its quote, and `reply` under the open card alone, so the rest stay short and near their
  passages; `edit` beside each age while the thread is open; `delete` asks first, in the actions' place, since nothing
  brings a thread back. A thread whose passage is gone carries a `passage gone` chip and stays in the list, last; two or
  more such follow a line that counts them, with `resolve all N`, since a new plan rewrites what it was asked to change
  and the comments on it lose their passages together. Resolved threads fold under a `Disclosure`. A comment or reply
  form sends on the key Settings names; Escape drops one that holds nothing new, and puts one with the operator's words
  aside, open with them, so one key never loses what was typed. A new comment's form offers labels under its field
  (`COMMENT_LABELS` in `src/lib/plan-comment-labels.ts`), each a fixed, firmly worded instruction to the planner that
  leads the comment. Once a comment is sent, resolved, deleted, or put aside, the cursor goes back to the plan after its
  passage, as a shared document's does, rather than to the top of the page. `Comment` again, on new words, moves an
  empty comment to them; one half written stays on its passage, so its words are never lost or carried to other words.
  While the plan waits on the operator, the choices its Decisions leave open (`src/lib/plan-decisions.ts`) are asked
  again under it, in its panel above its foot, each in a run's question's box (above), its options the radios of a
  `RadioGroup`, the planner's choice `recommended`: under the plan, not in the foot, so the decisions are read after the
  plan and answered just above the actions that send them; another pick is an answer, a line of the notes `Approve`
  carries and of what `Ask for changes` sends. The plan's card asks them the same way, so the picks are kept where both
  read them, in this browser until they are sent (`src/lib/plan-picks.ts`), never the journal, each holding while its
  decision reads as it did. An epic's plan asks them too, but its approval carries no note, so there an answer goes
  with `Ask for changes` alone and `Approve` waits while one stands. Since the panel is out of sight under a long plan,
  the line under the foot's actions leads with a jump to it (`DecisionsJump`), which informs rather than gates: no
  status tone, and `Approve` is never held back. It is named, though: while a plan has open decisions and its approval
  would carry no notes, the primary reads `Approve as planned` wherever it is offered, so its own words say whose
  choices it takes. The plan's actions are its panel's sticky foot (`PanelFooter`), so a long plan is approved or sent
  back
  from where it is read: the caller's own actions (a ticket's `Approve`, the foot's one primary, then `Save`, outlined,
  and `Skip the plan`, ghost), then a note on the whole plan and `Ask for changes`, outlined. The line under them says
  what goes with each; with open comments or a note, the primary reads `Approve with notes`. `Skip the plan` asks first
  in the actions' place, as a comment's Delete does. What an action did goes under that line, and stays once the plan
  turns read only. An approval, once the journal holds it, is a moment of its own: its words in the accent on the
  accent's tint, with a check, rising in, and the leaf a cleared item drops (Fun), then `Back to Attention`. A ticket's
  plan opens on its page; `/plan-editor` is kept as the editor's bench, linked from nowhere, over a sample plan on mock
  data only, so its behavior is tried without a ticket's state.
- **A chore** is a line in `canopy status`'s words (`choreLine`) in its latest run's state color, then how often it may
  start and its window, as the config and the CLI say it, its open findings less those dismissed, then how many were
  dismissed as `canopy status` counts them, and what its runs cost in the last 24 hours and 30 days. Its page's
  description says whether it is healthy (`choreHealth`), and its Schedule panel names what the config sets: `at most`
  always, a window or `when` only when set, since a default is no fact about the chore. A chore run is a row like a
  run's, its id as `chore:deps#2` (Names, below), with its findings as a chip on an `ok` run. A finding is one row
  (`ChoreFindingRow`) on a chore's page and a chore run's alike; an open one says how long it has been open, and on the
  chore's page has `dismiss` after its age, or once dismissed a plain `dismissed` chip and `undo`: still reported, only
  off the attention list. Its title is never cut: it is the finding's name, so it wraps. A row's own action is a ghost
  `xs` button in monospace in its head line, never a full button under the row; what it did goes under the row, once
  clicked.
- **Names** (`src/lib/refs.ts`): what canopy keeps by id is named as the CLI reads a reference, `KIND:ID`, in rows,
  trails, titles, and the tab alike: `run:41`, `review:4`, `chore:deps`, and in the same grammar `tick:2` and
  `memory:3`, which the CLI takes no reference for, so a list never shows a bare number that reads as a row's. A chore
  run has no reference of its own, so it is its chore's and its number, `chore:deps#2`, as GitHub writes an issue's,
  and a task's run the same, `task:4#5`, and an epic's plan run, `epic:2#3`. Each with a page has a link component
  that opens it (`RunLink`, `TickLink`, `ReviewLink`, `ChoreLink`, `ChoreRunLink`, `TaskLink`, `TaskRunLink`,
  `EpicLink`), used wherever it is named; a page's title calls the same function. A message is `#5`, as its
  conversation numbers it, and a worktree slot `#3`, as treehouse does. Nothing builds a reference in place. A PR is
  named as GitHub writes a reference, `org/repo#123` (`pullRequestLabel`; any other host's URL as written without
  `https://`), and only through `PullRequestLink`. A link into a GitHub PR, such as to one of its threads, is the PR
  all the same: its name goes in to the PR's page and its icon out to the thread.
- **The label goes in, the icon goes out.** A PR or a ticket named anywhere is its name linking to its page in canopy,
  then a small icon (`LinkOut`) opening the same thing outside canopy in a new tab, named for a screen reader and on
  hover (`acme/web#88 on GitHub`, `ABC-102 in the tracker`): `PullRequestLink`, and `TicketLink` when
  `tracker.ticket_url` is set. So one click from anything that names a PR reaches the PR's page, and one more its host.
- **A link out** (a PR, a ticket in the tracker, a finding) opens in a new tab with `rel="noreferrer noopener"`, shows
  its address without `https://` when it shows one, and ends in one icon (`LinkOutIcon`): GitHub's mark for github.com,
  bundled since Lucide has no brand icons, and `ExternalLink` anywhere else. A link never wears two icons. A ticket's
  links out sit in its page's header, under the title, so they are the first thing found (`TicketLinks`): a
  `LinkOutButton` per link, an `sm` outline button in the accent's monospace, its one icon first, the tracker's first,
  then each repository's PR, then the ticket's branch in each repository that has a branch link (design §18). A kind
  with more than one link is one button saying how many (`3 PRs`) that opens them as a menu, so the links stay one line
  however many repositories. The Work panel keeps each repository's PR beside its phase; those lines scroll inside the
  panel past a few, so its total cost, its actions, and the reply stay in reach.
- **A block's actions** (`BlockActions`, `src/components/block-actions.tsx`): what takes a block of a document
  elsewhere, a diagram's Mermaid source among them, sits in a row at the block's top right corner, over it, on
  `surface`, or in a plan's diagram's head, before `Source`: ghost `icon-xs` buttons, each named on hover, as a copy
  button is (below). The block's text, the form most wanted, is a copy button; its other forms are a menu after it, in
  words, as a drawn diagram's picture is (`Copy as image`, `Save as PNG`, `Save as SVG`: on `surface`, the PNG twice its
  size, the SVG cut down to what canopy keeps (D131), named for the plan, its kind, and its place,
  `ABC-102-plan-2-sequence-1.png`, or on a guide page for its title), and as a plan's table's rows are (`Copy for a
  spreadsheet`, tab-separated text and an HTML table together; `Save as CSV`, `ABC-102-plan-2-table-1.csv`), after its
  copy as Markdown. A cell a spreadsheet would run as a formula goes as text (`src/lib/table-export.ts`). They show
  while the block is hovered, holds the caret, one of them holds the focus, or their menu is open, and always on a touch
  screen, kept in place out of sight so nothing moves; a block marks itself `group/block` and is positioned. A plan's
  blocks are drawn by ProseMirror, so each keeps an element for its actions (`src/lib/block-slots.ts`) which the page
  fills through a portal, in its own tree. They are never printed.
- **Text to paste elsewhere** has a copy button after it (`Copyable`, `CopyButton`): a branch, a path, a session id, a
  review's commit, whole though the page shows its first 7 characters. A code block, in a plan, the guide, or rich text,
  has one in its corner (A block's actions), which copies its code as the fence holds it, no newline after its last
  line, so a command pasted in a shell waits for Enter; a diff's code has none. A path copies whole though the page
  shows it from the workspace root (`CopyablePath`); until the root is read there is no button, so a copy is never the
  short path. The button is a ghost `icon-xs` with the `Copy` icon, muted until hovered; a click shows `Check` in the
  accent, or `X` in `status-failed` when the browser refuses, and names what happened, and a toast says the same with
  the text it copied. In a dense list it shows only while its row is hovered or it has the focus, keeping its space so
  nothing moves, and always on a touch screen. The clipboard needs a secure context, so elsewhere there is no button
  and the text stays selectable.
- **A toast** (`Toaster`, `useToast` in `src/hooks/use-toast.ts`) says what an action did when the place it was done
  shows too little of it: a copy names what it copied, a draft's send what it sent. It sits at the bottom center of the
  window on `surface` with a hairline, a `Check` in the accent or an `X` in `status-failed`, its title, and a line under
  it in muted monospace, on one line with an ellipsis where it is cut. It closes on its own after a few seconds, held
  while the pointer or the focus is on it; F8 reaches it from the keyboard and Escape closes it. At most three show. A
  screen reader announces it. It never carries an action, and it is never the only place an outcome shows: the control
  that acted says so too, and a refusal is still a `Notice`. The one `Toaster` is rendered around the router, so a toast
  outlives the page it came from.
- **The note of what changed while away** is the one toast no action shows (`useAwayNote`, `src/lib/away.ts`). Shown
  again after it was hidden 10 minutes or more, the tab says in one line what changed meanwhile: what newly blocks work
  first, then the items cleared, the PRs opened, and the runs ended, each count of none left out, and nothing at all
  when every count is none; it stays longer than an action's toast, since it is read on coming back rather than seen as
  a click lands. Every count is read after the return, never told from what the tab held: the attention list as the
  stream sends it again, against the one the tab held as it was hidden, and the runs counted over the whole journal.
  With no fresh list soon after the return, as while the loop is down, it says nothing.
- **Every field the operator writes in to send** (a reply or note, a plan comment, a review request's notes, a draft or
  a lesson in their own words, the notice to workers) sends on the key Settings names, through `useSendKeys`: Enter by
  default, as a chat does; Ctrl+Enter (⌘+Enter on a Mac), Enter making a new line; or Button only. Shift+Enter always
  starts a new line, and an Enter that ends an IME composition only commits it (`src/lib/send-key.ts`). The key
  submits the form, so the form's submit checks what its disabled button does. The send button names its key in a
  keycap (`SendKeycap`) after its label, tinted with the button's own color; the keycap is `aria-hidden`, and the
  button carries the same keys as `aria-keyshortcuts`.
- **Behavior comes from Radix**, through the shadcn wrappers in `src/components/ui/`, and only they import it (the lint
  refuses `radix-ui` anywhere else): a button that is on or off is a `Toggle`, a part of the page that opens under its
  button is a `Collapsible` opened by a `Disclosure` (below), an option that is on or off a `Checkbox` (or, for the
  lightswitch rave alone, a `Switch`), a choice of a few options a `ToggleGroup`, or a `RadioGroup` when each is a
  sentence, and a row of an editor's controls a `Toolbar`, one tab stop with the arrow keys between them. Radix keeps
  their ARIA in step with their state, so a component never writes it by hand. Two stay native on purpose: a
  transcript's tool call is a `<details>` (above), and rich text's `show N more lines` (`MoreLines`) shows more of text
  already on screen rather than opening a part, so it is a plain button with `aria-expanded`. A new wrapper is
  shadcn's, added or ported as `button.tsx` was.
- **Modes and disclosures** follow one rule each, so a control says which it is before it is clicked:
  - A **mode**, a way of showing what is already there, is a pressed `Toggle`, a ghost `xs` button raised while on,
    labelled with the mode and never with what a click does: Pretty, By call, a transcript's All open. It names the
    mode in both states; `aria-pressed` says which. A list's order, which has two values and no off, is the one
    exception (`OrderToggle`): it names the order in force, the arrow saying it flips.
  - A **disclosure**, what opens a part of the page under it, is a `Disclosure` (`src/components/disclosure.tsx`) on
    its `Collapsible`: a ghost `xs` button, a chevron that turns down while open, and what it does in words, `Show
    <what>` closed and `Hide <what>` open. A row that opens to its own body, a transcript's tool call or model call, is
    the row itself, a chevron at its end.
  - Two of either are one: a pair that does and undoes (Open all, Close all) is one `Toggle` (All open).
  - A panel header's modes sit together, after what the panel is about, behind a hairline rule.
  - A panel kept at hand but seldom read whole arrives folded (`FoldPanel`, `src/components/fold-panel.tsx`): its
    header, a readout that says what it holds in a few words, and a `Disclosure` that opens its rows under it, built
    only once opened. A run's Memory is one, a review draft's `What the reviewer found`, and the Prompt on a run's, a
    tick's, and a chore run's pages (`PromptPanel`).
- **Buttons come in three sizes**, each one look: the default (`h-9`, `text-sm` at 500) in a form and a panel's foot;
  `sm` (`h-8`, the same type) in the header and for a link out, whose label is the accent's monospace at that size and
  weight (`LinkOutButton`); and `xs` (`h-6`, `text-xs` monospace at 400, as a readout beside it is) in a panel's header
  and a row, a `Toggle` or a `Disclosure` included. A button never sets its own size or weight.
- **Options that are each on or off** (the ticker's topics) are a row of checkboxes (`Checkbox`), each inside its
  label, so a click on the word toggles it too. The row is a `fieldset` named by the line beside it.
- **A choice of a few fixed options** (a theme, the ticker's speed, the send key) is a segmented control
  (`ToggleGroup`): the options in a well on the canvas, the picked one raised on `surface-raised` with `shadow-xs`. It
  is a radio group, so one option is always picked: the arrow keys move between them, Space picks one, and Tab leaves
  the group.
- **A choice of one among an agent's lettered options** (a plan's open decision) is a radio group (`RadioGroup`),
  since a segment cannot hold a sentence, drawn as a run's question's options are (`LetteredOption`), so the two read
  as one thing: each option a full-width row that is its radio, its letter in a small square that turns to a check in
  `status-done` once picked, `recommended` after the agent's own. It is named by the question it answers.
- **A choice of repositories** is a repository picker (`src/components/repo-picker.tsx`), never a chip or a segment for
  each, since a workspace may have dozens: an outline `sm` button in monospace saying what is chosen (`every
  repository`, muted, while it narrows nothing; a name; two; then `3 repositories`), opening a list under a field that
  keeps the names holding what is typed (cmdk, through `src/components/ui/command.tsx` alone). A filter (`RepoFilter`)
  takes several, picking one keeps the list open, and what was chosen as it opened is listed first, so nothing moves
  under the pointer; it is kept in `?repo=`, replacing the history entry as a filter field does. In a form
  (`RepoSelect`) it takes one, and picking it closes the list; an epic's form (`ReposChoice`) takes several, as a
  filter does, with no `every repository`, since none chosen names none. The runs page's filter by model and the
  reviews page's by author (`ChoiceFilter`) are the same picker of one, each name whole, as a gateway can list dozens
  of models; the button, list, and item are `src/components/picker.tsx`, which all of them build on.
- **A config page** (`ConfigForm`, `/settings/limits`, which Settings links to from a one-line panel so Settings stays
  short): the keys in a few bands by what they govern (`CONFIG_GROUPS` in `src/lib/config-settings.ts`), a band whose
  keys share a unit cut into labelled parts (`h3`) so the unit never decides where a key lives, and a key no band names
  in an `Other` band. A row is the key in words over its name in the file in monospace, a chip for where its value comes
  from (its meaning on hover and in the page's help, said once), and how far the page may take it; its control sits in
  one fixed column every row shares, its unit after the field as on Settings, so the controls line up. The page is one
  column capped near `max-w-4xl`, each band's heading over its panel a step above the rows' labels. An index of the
  bands sits beside the form, sticking as the page scrolls, or in a line over it in a narrower pane: each band counts
  its keys set in this workspace and, apart, its rows changed and unsaved, and the band in view is marked. Each row is
  its key's anchor (`#policy.max_resume_attempts`), so a refusal, the guide, or a note can link straight to it; opened
  there, the row lights once. A filter field over the form, kept in `?q=` as a list's is, narrows the rows to those
  whose label, key, or band's blurb holds it, and says how many; a row with an unsaved change stays whatever it says, so
  a change is never hidden, and the index dims a band left empty. Escape there empties it, since the usual visit is one
  row and out. A key at its strictest shows its value as text beside a lock, and how it loosens, never a control with
  every other choice disabled, which reads as broken; a band of keys that only get stricter says so once, with a lock,
  in its header, and a switch is named for what it does, never `on`. Dropping an entry only the file adds back, an
  authorized replier or a list's last, asks first, inline. A list keyed by repository lists only the repositories with a
  value of their own and a repository picker to give another one, so a workspace of many repositories does not get a
  field per repository. A changed row wears an accent hairline at its start and its old value in its meta line. A row
  whose value is not its default says the default, and offers a reset where the page may take it there (within its
  bound, or toward stricter); a reset is an ordinary change, listed and saved as any other. One save bar, sticky at the
  page's foot, appears once something changed, so the page at rest shows no actions it cannot take and a change far down
  the page is never left unseen; its height is held at the page's end, so its coming moves nothing. It lists each change
  as `key: old → new`, folding the rest past a few, and warns when a change is one only the file undoes, before Discard
  and Save. A save reads the file again, and the bar stays while its `Notice` keeps what the save did over the fresh
  form.
- **A page of the operator's files** (`InstructionsForm`, `/settings/instructions`, linked from Settings as a config
  page is): a panel per file, all shown at once, each saved from its own foot, since each save is a write of its own,
  never one save bar for the page. The index beside them is a config page's: each entry its panel's anchor, marking a
  file runs refuse in `status-failed` and an edit not saved in the accent, which its panel also wears as a changed row
  does. Leaving with an edit not saved asks first, as the plan editor does (`ConfirmLeave`). A file that is not there
  offers Create, which opens its editor, rather than an empty one waiting; a delete asks once more inline, from the
  quietest button at the foot's end. Its kept versions open under the panel, and a restore is an edit in the editor,
  saved as any other, never a write of its own.
- **An action** is a button in the foot of its subject's identity panel (the detail skeleton, above), under a
  ticket's reply (The answer, above), or under its form, with one line under it (`Notice`): what the action did, in the
  CLI's words, or its refusal in `status-failed`, naming the guard. An action that kills something asks once more
  inline, never through a browser dialog. One that cannot be undone asks for its subject typed out: Forget opens a form
  in `status-failed` that says what it drops and keeps, and its button stays disabled until the field holds the
  ticket's key exactly. Until then Forget is the quietest of the row, a ghost button in `status-failed` text at its end,
  since the loudest button is the one clicked first. The line under the actions is absent until one has said something:
  a blank band at a panel's foot reads as a layout fault, and it appears under the button that was just clicked, so
  what moves is below the operator's eye. A failure that is not a refusal says what happened in canopy's words, never
  the browser's (`failedText` in `src/lib/outcomes.ts`): no answer at all is `canopy did not answer: is canopy loop
  running?`, and a status with no words of its own says whether the action was done. A public ticket has no Stop, since
  its queue label authorizes it; while a worker runs on one, a muted line stands in Stop's place saying how to stop it.
- **A choice of persona** is a menu (`DropdownMenu`) on an outline `xs` button naming the choice
  (`src/components/personas-menu.tsx`): a ticket's agent's picks one, a review request's checks several. Each item is
  the persona's name in monospace over its description, its file's own or else its opening sentence, in muted `text-xs`:
  the name is the item's accessible name, the description its accessible description. A persona canopy would refuse is
  disabled, with why on hover. The menu ends, after a hairline, with what goes back to the config.
- **A choice of model** (`ModelPicker`, `src/components/model-picker.tsx`) is the same menu over the models the runtime
  lists, read as a row naming a model shows, so one gone is marked before the menu opens: the button, then where it
  comes from in muted `text-xs`. A ticket's agents (`src/components/ticket-agents.tsx`) share one grid, a row per
  agent, its name, its persona, then its model, so the conversation under the panel stays in reach. A model's id is
  monospace, and a long one ends in an ellipsis, whole on hover; the runtime's default names none, so its button reads
  `runtime default` in muted sans. Each model's variants are items of their own under it, indented, each `@variant` to
  the eye and named whole for a screen reader. A choice saved is confirmed in its row, `saved` or `cleared` in
  `status-done` in place of where the model comes from, so nothing below moves. The menu offers only what the server
  would take: the model chosen now, when it is not one, is a disabled item with why under it in `status-failed`, and a
  model gone from the list marks its trigger in `status-failed`, as its attention item's chip is. A list that cannot be
  read says why, offers no model, and has a `Read again` item. While a choice saves, its trigger is `aria-busy` and
  `aria-disabled`, never `disabled`, so the focus the list hands back stays on it.
- **Attachments** (`src/components/attachments.tsx`, DESIGN §22) are a section with a `panel-label` heading, under the
  verbs at the foot of a ticket's or a task's conversation, beside the reply that says what to do with them: each file
  a row of its name in monospace, its size muted, and a ghost `icon-xs` ✕ named `Remove NAME`; an outline `xs` **Attach
  a file** beside the heading opens the browser's file picker. A muted line says how much of the limits it holds. The
  page refuses a file over the bound or not UTF-8 before sending it, as an `ApiError` naming the CLI's guard, so it
  reads in the `Notice` as the server's refusal would.
- **A limit something is stuck at** (`GrantLimits`) sits under a ticket's actions, after its reply, but under the run on
  a broken run's item, which asks for another try first, and in the foot of a PR's Pull request panel. While something
  is stuck it is a block on the `status-failed` tint, the color its `attempt_limit` chip wears, so it stands out from
  the panel: a line led by `At its limit.`, then a row per limit whose runs have reached it, what it counts in
  monospace, its runs against it in `status-failed`, and an outline `Allow one more` button at the row's end. Under the
  row, in muted monospace, is the CLI's command for the same grant with a `Copyable`: in the text, not a tip, since it
  is something to type. What the grant did goes under the rows (`Notice`), untinted once nothing is stuck; the row
  leaves once the limit is above its runs. A limit with room left shows nothing.
- **A review request** (`ReviewRequestForm`, `ReviewRequestStatus`) is how the operator has canopy review a PR the loop
  does not own (DESIGN §21). The reviews page leads with a `Review a PR` panel above the list, whose form is one column
  capped at `max-w-3xl`: the PR's URL in a monospace field, and under it a line it always holds, so nothing below moves
  as it changes: the PR's reference once canopy would take the URL, that it is not a PR's URL, before it is sent, or,
  empty, that a link into the PR will do. Then the notes, always open since the operator often has some, under a
  sentence-case field label, never a `panel-label`. Then who reviews it, one row with nothing folded: `Persona` and its
  menu, `Model` and its menu (A choice of model), and at the row's end `Review`, the form's primary, with its keycap
  and the CLI's command on hover. The form ends on one quiet line saying its review is a draft that posts nothing until
  published, which a refusal replaces. On success the form opens the PR's page. It takes no repository: the overseer
  finds the PR's. A PR with an open request wears a `requested` chip after its review in the list. On a PR's page the
  request is a line in the foot of its Pull request panel, with an outline `Stop` while it is open, or how it ended;
  while none is open on a PR the loop does not own, the line's end holds the menus and an outline `Review this PR`.
- **A review** (`/pull-requests/reviews/$id`) is canopy's shadow PR review, kept in the journal (D114); on a PR the loop
  does not own it is also a draft the operator may publish, word for word, as their own (A review's draft). The page
  holds the review's fields, its findings as a list linking to each one's card, and the diff, a panel per file. Its
  header has the PR's link out, as the PR's page does. Each fact is said once: the description is the run's status
  alone, and the Review panel's header has no dot. The panel leads with the reviewer's summary, the answer the operator
  came for, then the `harness` line when the harness decided the status, then the verdict, in its worst finding's color
  with its impact chip (its one home), the PR, with the PR's other reviews on a muted line under it, the ticket, the
  commit, when it ended, and what it spent. A diff is a monospace table: the old and new line numbers, the `+` or `-`
  in `diff-add` or `diff-del`, and the line, its row on that token's tint; a hunk's header on `surface-raised`; long
  lines scroll sideways inside the panel, while a finding's card and a fold keep to the panel's width at its left edge,
  so one long line never carries a card's text out of reach. The code is colored by the file's language
  (`src/lib/languages.ts`) in the `syntax-*` tokens, each read at 4.5:1 on an added or removed line's tint too; Shiki
  tokenizes in the browser (`src/lib/highlight.ts`, D121), a stretch at a time with the page running between them, so a
  long diff never holds a click; a line shows plain until its file's grammar has loaded, and stays plain for a language
  canopy does not map, a file or a line too long to be worth it, or a grammar that fails. A diff over 2,000 lines folds
  (`DIFF_BUDGET`, `src/lib/review-folds.ts`), since one at the server's bounds drawn whole is 150,000 elements: the
  page draws the lines around each finding, then whole files in order while they fit, then the first lines of the rest,
  and says so in a muted line above the first file. Each run of lines it leaves out is a fold, a row with a ghost `xs`
  button, `Show 60 hidden lines`, which draws the next step; a fold only adds, as rich text's `show N more lines` does,
  so it is a plain button, not a `Disclosure`. The panels take any card anchored at a line (`DiffPanels`), so a PR's
  threads sit on a run's diff as findings do on a review's. A file's panel folds away whole on `Hide diff`, a
  `Disclosure` at its header's end, to its header and a muted line counting what it hides. Above the first file, an
  outline `xs` button names the file types shown and opens a menu of them, each a checkbox item, so several flip in one
  go; a link from the findings list to a card ticks its file's type and opens its panel, so a link never lands on
  nothing. A finding's card (`FindingCard`) sits right under the line it names, or under its file's header when the
  diff does not show the line, or in a Not in the diff panel after the files. A card holds its number, its severity as
  a chip (`blocking` in `status-failed`, `major` in `status-blocked`, as the attention list's reasons; `minor` plain),
  its title, its location, and its detail as rich text, with `dismiss` at the end of its head line; a dismissed one has
  a `dismissed` chip, its title muted, `undo` in place of `dismiss`, as on a chore's finding. On a review of one of the
  loop's own PRs, each finding in the list the operator has not dismissed has a checkbox before its number, and under
  the list `send to a worker` sends the ticked ones together, as `canopy send` does. The list of reviews is a
  `ReviewsTable`: its run state's dot and its verdict in its worst finding's color (`verdictTone`), so a review with a
  blocking finding never reads as calm as a clean one, and the worst in words, since color alone says nothing to some
  (`verdictText`: `3 findings, 1 major`); the review's link; its ticket, its impact, then in the free column the PR,
  its title in what room the rest leaves, and the commit's first 7 characters, then cost and age.
- **A review's draft** (`ReviewDraftPanel`, DESIGN §34), on a review of a PR the loop does not own, leads its page,
  which is the draft's one record: the title is `review:5 Your review of acme/api#14 by carol`, and the description the
  draft's state, its status chip (`REVIEW_DRAFT_TONE`: staged and unconfirmed in `status-blocked`, publishing as
  running, the rest plain, since nothing waits on a draft), its version, and what the status means. The `Draft review`
  panel comes first; canopy's Review fields and Findings fold under it into one `FoldPanel`, `What the reviewer found`;
  the diff follows. The panel's header names the version, then a muted line saying it is what would post, word for
  word, on which commit, and to read it first; a `status-blocked` line when the PR's head has moved past that commit;
  the body as `MemoryText` with a ghost `xs` `edit`; its comments as rows linking to their cards; every version in
  muted monospace; and in its foot the one way canopy posts as the operator, as a PR's thread drafts are sent (A PR's
  threads, below): a default `Publish version N`, which submits it, and beside it an outline `Start the review on
  GitHub`, which stages it, each with its command on hover, and a muted line by them saying what posts, as you, on
  whose PR, and on which commit. A publish says what it did in a toast; staged or published, the foot says so in one
  line linked to GitHub, never a raw URL. A ghost `Discard` asks in its place, as skipping a plan does. On the diff, one
  card per point of the review: each finding's card is its comment's too (`ReviewPointCard`, a draft's card, above,
  never a `FindingCard` beside a comment's card), with a chip, `in your review` or `left out`, and one ghost `xs`
  control where a finding's `dismiss` is: `leave out` dismisses it, `put back` takes that back, so the two are one
  choice, as DESIGN §34 ties them. A comment the operator added keeps a card of its own under its line, and while the
  draft waits, each line of the new side has a ghost `+` beside its number, shown on the row's hover or its focus,
  which opens a new comment's card under the line. A review whose request made others of the same commit in other
  personas names them in a muted line, each a `ReviewLink`, and that each is a draft of its own: publishing one changes
  none of the others. Outside its review's page a draft is its status alone (`ReviewDraftChip`), after the verdict in a
  review's row and a PR's, where its state is, so the list's left edge says which of the operator's reviews wait on
  them.
- **A PR** (`/pull-requests`, `/pull-requests/pr?url=`) has a section of its own. A PR's row: where it stands, which is
  the run working it now while one does, then its latest review and its verdict, in its worst finding's color (`not
  reviewed` muted), its draft's chip, and `requested` while the operator's request is open; the PR; its unit's phase as
  a chip; then its ticket and title in the free column, and its age. The ticket shares the free column with its title:
  a column of its own would not fit a 1280px window. Its page: the PR's name as the title, then its own title as its
  worker reported it, else its ticket's, with its phase as a chip; its description is where it stands, as its row leads
  with it, and for a PR canopy only reviews, `canopy only reviews it`, said there alone. A link out follows, saying
  where it goes rather than repeating the title. Then panels: its fields, with a grant of another review in its foot
  when it is at its review limit; its review threads when canopy has read them or holds a draft for it, led by its
  feedback plan while that waits on the operator; then its reviews, the runs that pushed to it, each with its range in
  the PR's repository as a ticket's runs list names it and its commits there under it, with the kick canopy pushed
  after it, so the list reads as the branch's history, and its decisions, each a `ListPanel`, and no Runs at all on a
  PR with no ticket, since runs are a ticket's.
- **A PR's threads** (`ReviewThreads`, DESIGN §29) are its coworkers' review threads, as canopy's reader last read
  them, on the diff the latest run kept, under every `trust.review_replies` setting, with the replies runs drafted under
  them. The PR's detail says up front whether there are any, so their place is held before they arrive. A `Review
  threads` panel leads: what `trust.review_replies` means for them in a line, when the PR was read and at which head,
  the run whose diff they sit on, or, with none kept, why its latest run kept none in its Diff panel's words, a
  `status-blocked` line when the PR's head is past the kept diff's commit, a `Drafts` list of every draft in the order
  their cards show, whose links open the card's file as a review's findings list does, and in its foot `Send N waiting`,
  which sends every waiting draft as one comment review, and an outline `Start a review on GitHub` beside it, which
  stages them in a pending review instead, with a muted line saying what each does; while the PR holds a staged review,
  neither shows, and a line links to the PR's files on GitHub to finish it. While its ticket has a current feedback plan
  (docs/design §32), a `Feedback plan`
  panel (`FeedbackPlanPanel`) comes before the `Review threads` panel while the plan waits on the operator, so its
  Approve is in the first screen, and after it once approved or spent; where it sits is settled as each plan is first
  read, so one approved meanwhile stays put. The panel: `feedback-plan:N` and its status as a chip in its header
  (`waiting on you` and stale in `status-blocked`, approved as running, spent plain), a muted line of who planned it and
  what its status means, a row per item (a `Checkbox` until a resume spends it, its number, the first line of what was
  said as `MemoryText`, and where it is, a router `Link` to the thread's card or a link out; under that, muted, its
  proposal as a chip in its tone, its author, and the plan's words), and in its foot the operator's words and `Approve
  whole` or `Approve N of M`, its command on hover, an approval done as the `ApprovedBand` a ticket's plan gets, then a
  `Disclosure` of the plan's file, laid out read only as a document (`PlanDocument`, as a task's report is), loaded
  once opened. An item an approval did not tick is `for the next plan` wherever the page says so,
  and its box is named `approve item N`, never `left out` or `leave`: `leave` is a proposal, to leave the item be, which
  ticking it approves; the CLI's flag stays `--leave`, on the button's hover. Each proposal's chip has a quiet tone of
  its own (`proposal-*`), so `change`, the one that edits code, stands out, `decline` and `ask` sit apart from it and
  from each other, and `leave`, which does nothing, stays plain. Then the diff (`DiffPanels`), each thread's card
  (`ThreadCard`, `surface-raised`) under its line, under its file's header when outdated or off the diff, and a `Not in
  the diff` panel for the rest. A thread's card: where it is in muted monospace, `outdated` and `resolved` chips, each
  comment's author, a `bot` chip, `sent by you` on one the operator sent, its age, a `LinkOut` to it, and its body as
  `MemoryText`, plain, never Markdown or a link; a draft's text the same. A thread the feedback plan covers carries its
  proposal above its drafts (`PlanProposal`, an inset rule on the thread's card, not a card of its own); a `change` its
  resume is still to act on, over a waiting draft, says in `status-blocked` that the resume writes a new reply there and
  sending the draft first answers ahead of it. A comment's `<details>` blocks are the one thing read in it
  (`CommentText`, `src/lib/details.ts`): each folds, as on GitHub, under a `Collapsible` row of a chevron and its
  summary, and a closed one that folds a hidden character carries `hides a character` in `status-failed`. Only bare
  `<details>`, `<details open>`, and `<summary>` are read, so a dropped tag hides nothing. A draft's card (`DraftCard`,
  a draft's card, above) heads with `Draft`, `run:N` and its number, its status as a chip (`DRAFT_TONE`: waiting,
  unconfirmed, and staged in `status-blocked`, refused in `status-failed`, sending as running, the rest plain), the
  run's stance as a muted word, `your text` once edited, and its hash, the one a send carries; then the harness's
  reason for a status other than waiting, a `status-blocked` warning when it replaced a draft the operator edited, and
  its text as `MemoryText`, struck and muted once superseded or dropped. A thread's draft that stages a reaction says
  so in a muted line under the text. Its verbs: `Send` (default) on a waiting draft, `Edit` and `Drop` on one waiting or
  unchecked, ghost `Undo` on a dropped one, and a `LinkOut` to a sent one; `Edit`'s form holds, on a thread's draft, a
  `Reaction` `ToggleGroup` of GitHub's eight, each an emoji named for screen readers. What each verb did goes under it
  (`Notice`), in `canopy draft`'s words, and a toast says what a send did as well, since a send speaks for the operator
  outside canopy and the line under the card leaves with its attention item at the next tick. A ticket's own drafts
  (`TicketDrafts`) are a `Drafts for the ticket` panel under the ticket page's grid, shown only when it has any, each
  card naming the issue it goes to in monospace, as text and never a link, since a worker named it.
- **Search** sits atop the nav on every page (`SearchBox`, a `SearchField`): a magnifier, the field, and `/` in a
  keycap, its shortcut from anywhere but a text field; while the field holds text, a ghost clear button takes the
  keycap's place. An empty field empties the search page if it is open, and leaves any other page as it is. Enter on a
  task's reference alone (`task:4`) opens the task instead of searching. The search page has a panel per source with
  hits, in the server's order, its count in the header (`newest 20` when the source has more). A hit is a row: where it
  opens, its label as a chip, the snippet with the query's words marked on the accent's tint (`src/lib/search.ts`), and
  its age. A snippet links nothing, since it may cut a URL short. While the next query's hits load, the last ones stay,
  dimmed to 60%. While empty, the field's end also holds the jump palette's keys in a keycap that opens it. After the
  journal's panels come the runtime's sessions' two, outside canopy then canopy's, each only with hits, their rows the
  Sessions page's with the words marked in the title; a subagent's, found apart from its parent, carries its chip.
- **The Sessions page** (`/workspace/sessions`, `SessionRows`) lists the runtime's sessions under Workspace, beside the
  runs: one panel, its header naming whose they are, with the group word `whose` and two filter chips, `outside canopy`
  (the default) and `canopy's`, then, each after a hairline, an `archived` toggle chip (`aria-pressed`), while the list
  is narrowed to a directory the group word `in`, the directory's end in mono, the whole in its tip, and a ghost icon
  button that clears it (`Clear the directory`), and the count. A row reads where it opens, then its chips (`subagent`,
  `archived`), its title in medium weight, as a run's is, its cost, and its age: one of canopy's leads with its run's
  reference, linking its page, and one outside with its directory's last two parts in mono (`…/acme/infra`), the whole
  in its tip, so the title keeps the width, a muted link that narrows the list to that directory (`?directory=`) until
  it is narrowed, and the command that reopens it under its title, a `Copyable` that wraps at spaces first and shows its
  button while the row is hovered or focused, named for the session. A subagent's row follows its parent's, marked by
  its `subagent` chip, which names the parent to a screen reader; titles are not indented, so every title starts at the
  same place. A line under the list, in muted text, says how far the loop's read has come, and holds the one link to the
  longest list and back. At `sessions.search = "off"` the panel is one `Empty` saying how to turn it on, and the header
  holds no count.
- **The jump palette** (`JumpPalette`, `src/components/shell/jump-palette.tsx`) jumps to a ticket from anywhere: `⌘K`
  opens and closes it, from a text field too, as a `Dialog` in the window's top sixth over the canvas. Its field is over
  the tickets viewed last, newest first, without the one on screen, so `⌘K` Enter goes back to the ticket before it;
  typing narrows them by key or title and lists the other tickets that match under them, and with none, the journal's
  search for the words. A row is the key, the title, where the ticket stands now in its state's color or its phase
  muted, and for a ticket viewed, how long ago. What was viewed is this browser's alone (`src/lib/recent-tickets.ts`),
  never the journal, and a ticket the journal no longer holds leaves it.
- **The review dialog** (`ReviewDialog`, `src/components/shell/review-dialog.tsx`) asks for a review from anywhere:
  `R`, with no modifier, from anywhere but a text field or the plan editor (the rule `/` follows), or a GitHub PR's URL
  pasted outside a field, which it fills in, opens it; on a PR's page, `R` fills in that PR's while no request of it is
  open, as one is once the dialog's own goes through. It never opens over another dialog. It is a `Dialog` placed as
  the jump palette is, holding the reviews page's form (`ReviewRequestForm`), one component for both so they cannot
  drift. A request that goes through closes it and opens the PR's page; a
  refusal keeps it open, its `Notice` naming the guard. What is written or pasted outlives closing it, kept in the tab's
  `sessionStorage` (`src/lib/review-request-draft.ts`) until a request goes through or the operator signs out. A URL
  the page filled in is kept only once something in the form is written or picked, with the draft it belongs to, so an
  untouched one never follows the operator off that page.
- **The ticket dialog** (`TicketDialog`, `src/components/shell/ticket-dialog.tsx`) starts a ticket from anywhere: `T`,
  with no modifier, under the rule `R` follows, never over another dialog. It is a `Dialog` placed as the review
  dialog is, holding the tickets page's form (`StartTicket`), so they cannot drift. A ticket that starts closes it and
  opens the ticket's page; a refusal keeps it open. Beside the button, a `Checkbox`, `Plan it first`, starts as
  `policy.plan` is in Settings and is sent only when it differs from the policy. Under the key, a `Disclosure` opens a
  row for each of the ticket's agents in the order the ticket meets them, each a persona menu and a model menu naming
  its default until one is picked; folded, the disclosure says how many picks there are.
- **Signed out**, the whole page is the sign-in card, centered on the canvas: no shell, nothing from the journal.
  Signed out by a 401 to an action, the card says under its heading, in `status-failed`, that the action was not sent.
  A reply being written outlives the page that held it: the reply form keeps what is written, with its submission id,
  in `sessionStorage` per ticket or chore until a reply is recorded (`src/lib/reply-draft.ts`), so after signing in
  again it is still in the box. Signing out on Settings drops every draft in the tab, so the next person to sign in at
  it sees none.
