# canopy web UI: design

The visual and interaction rules for `ui/`. Normative, like `docs/design/`: if a component and this file disagree,
this file wins until it is changed in the same PR. How to work in `ui/` is in `AGENTS.md`; why it exists is D079.

## Direction

An operations inbox: a control room's at-a-glance state, kept calm enough to read a worker's words and answer
them. Data sits in monospace readouts on quiet surfaces, separated by hairlines, on a plain canvas. One accent color
marks what is live, selected, or the action to take; what is selected in a page sits on its tint. Each section of
the nav has a color of its own, for a little fun and a sense of place: its icon, the nav's highlight on it, and the
trail over its pages wear it, and an aurora of them runs under the header. Status color is reserved for state, and a
counter wears the color of what it counts; section colors never mark state, and nothing else is colored for
decoration, but the fun's own (Fun, below). Both themes' neutrals carry the accent's indigo hue, so the canvas has
color of its own: dark is a deep indigo slate, light a lavender grey and white. Dark is the one the operator lives in;
neither is the lesser theme.
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
| `status-running` | A run working. Pulses. |
| `status-blocked` | A run that asked a question, and anything else waiting on the operator. |
| `status-stopped` | A run the operator stopped. |
| `status-done` | A run that finished. |
| `status-failed` | A run that failed, crashed, or left no result. Also shadcn's `destructive` and refusals. |
| `section-attention`, `-runs`, `-worktrees`, ... | Each nav section's color (rules below). Identity, never state. |
| `diff-add`, `diff-del` | A diff's added and removed lines: a 12% tint behind a line, and its `+` or `-`. |
| `spend-overseer`, `-idle`, `-workers`, `-chores`, `-reviews`, `-dry-run` | The spend chart's series, as fills only. |
| `syntax-key`, `-string`, `-number`, `-literal` | JSON's keys, strings, numbers, and literals, in agent output. |
| `flair-yellow`, `-red`, `-green`, `-cyan`, `-blue`, `-purple` | The ticker's RuneScape chat colors, and only those. |
| `buddy-eye`, `buddy-pupil` | Sprig's googly eyes: the white and the pupil, and its rim. |
| `buddy-leaf` | The sprig on Sprig's head. A green of its own, yellower than `status-running`'s, its near twin. |
| `buddy-hat` | A hat's felt: a dark grey, and the propeller's stem. |
| `buddy-hat-band` | A hat's band, pompom, and trim: a plum no status wears. |
| `buddy-hat-gold`, `-cloth`, `-blue` | A hat's gold, its white cloth (outlined to show on white), a wizard's blue. |
| `buddy-keyboard`, `buddy-key` | Sprig's keyboard: its case and its keys. A key pressed lights in the accent. |

Rules:

- **No raw colors outside `tokens.css`.** No hex, `rgb()`, `oklch()`, Tailwind palette classes (`bg-zinc-800`,
  `text-white`), or arbitrary color values. `npm run lint` fails on them (`scripts/check-source.mjs`).
- **No `dark:` in components.** Both themes are first-class and come from the same tokens. If a component looks wrong
  in one theme, the token is wrong: fix the value in `tokens.css`, for that theme. The lint fails on `dark:`.
- **Text reads at 4.5:1** (WCAG AA for small text), in both themes: every token used as text (`foreground`,
  `muted-foreground`, `accent`, each status, section, diff, and syntax color) on `background`, `surface`, and
  `surface-raised`, and each status on its own tint up to 20% (a chip, a destructive button, a question's bubble), in a
  selected row too. `src/styles/tokens.test.ts` measures every pair from `tokens.css` and fails below it, so a token
  change that drops one fails `npm test`. Text is never faded with `opacity` to look quieter: that is what
  `muted-foreground` is for, and an opacity under it drops below AA. Only a disabled control, and a state that passes
  (search's last hits while the next load), dim. The ticker's `flair-*` colors are decoration, not held to it.
- **Status colors** work three ways, in both themes, on `surface` and `surface-raised`: as a dot (`RunDot` in
  `src/components/status.tsx`), as text, and as a tint (`bg-status-blocked/8` behind a question). Map a state to its
  classes through a `Record<State, string>` written out in full, never by building a class name from a string:
  Tailwind only generates classes it can see.
- **Worktree states** borrow the run colors (`src/lib/worktree-state.ts`): `working` is `status-running` (it does not
  pulse; the run it names does, on the runs page), `held` is `status-stopped`, `dirty` is `status-blocked`, `broken`
  is `status-failed`. An `idle` slot is a hollow ring in `muted-foreground`: nothing holds it, so no status color
  claims it.
- **Section colors**, one per nav item: Attention rose, Tickets sky, Pull requests gold, Reviews fuchsia, Runs violet,
  Chores orange, Spend azure, Ticks lime, Worktrees teal, Settings lavender (`src/lib/sections.ts`; the current one
  from `useSection`). They go on the nav's icons and highlight, the first step of the page header's trail, and the
  header's aurora, and nowhere in a page's data: there a color is a state's. A page in no section (the 404) takes the
  accent.
- **Spend series** (`src/lib/spend.ts`) color a kind of agent run in the spend page's chart and its legend, and
  nowhere else: they are fills, never text, so the legend's words are `muted-foreground` beside a swatch. Idle overseer
  spend is the overseer's hue, lighter, so it reads as part of it. Each reaches 3:1 on `surface` in both themes, WCAG's
  bar for a graphic, which `tokens.test.ts` measures.
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
- Sizes: `text-xl` page titles, `text-sm` body, `text-xs` secondary and data-dense rows, and `text-2xs` (11px, defined
  in `tokens.css`) for the smallest print: a chip, the stream's state, the rail's labels and spend windows, and a
  `panel-label`. Nothing larger, but a counter's value (`text-3xl`), and nothing smaller or between the steps: no
  arbitrary sizes (`text-[0.625rem]`).
- **An icon is the size of the text it sits with**: 16px (`size-4`) beside `text-sm` and in a button of the default or
  `sm` size, which sets it; 12px (`size-3`) beside `text-xs` or smaller, in an `xs` or `icon-xs` button and a segmented
  control, which set it too, and as a link out in a row. Nothing between, but a checkbox's tick, which fills its box.

## Shape and space

- Hairlines: 1px `border` everywhere. No shadows except `shadow-xs` on a pressed segment.
- Radius: `rounded-md` (8px) for panels, buttons, and fields, `rounded-sm` (6px) for chips and nav items, `rounded-xs`
  (4px) for a mark smaller than a line of text, a checkbox or a slot's square. The scale is in `tokens.css`; no
  arbitrary radius (`rounded-[4px]`), which `npm run lint` refuses.
- The shell: a 3rem header, a 13rem side nav, content capped at `max-w-[112rem]` with `p-6` and `gap-6` between
  blocks.
  The header stays put and only what is under it scrolls (`page-scroll`), so the header spans the window's width
  and a scrollbar, or the gutter kept for one, sits beside the rail and the page, never beside the header: the
  browser paints the window's own gutter with the canvas color alone, so when the window scrolled, the header
  stopped short of its edge. The side rail runs the full height of the page, and what it holds sticks: a column as
  tall as the window under the header. Printed, the shell is not held to the window and shows the page whole; a
  screenshot test does the same by growing the window to the page (`growToPage` in `e2e/helpers.ts`).
- **The rail** holds, top to bottom: the search box, the nav, the runs working now, the spend, and a footer
  (`src/components/shell/rail.tsx`). The nav lists the sections by how often the operator opens them (`SECTIONS` in
  `src/lib/sections.ts`): what they work in first (Attention, Tickets, Pull requests, Reviews), then what they check
  now and then, with Settings last. Each nav item says on hover what its page holds, and each spend window what it
  covers, as a native `title`; a spend window opens the spend page over its week or month. Each block under the nav
  is a hairline and a `panel-label` over its content. The working runs are those running first, then those waiting
  on the operator's answer, each oldest first, a ticket's latest run alone: a dot in its state's color, the ticket's
  key, how long it has run (or `waiting on you` in `status-blocked`), and the ticket's title under it, opening the
  run's page; at most four, then `+N more` to the runs page, so the sticky part fits an 800px window.
  The spend is the last 24 hours and the last 30 days from `GET /api/spend`, on the stream, in small readouts: it
  is shown nowhere else, but for the lifetime total Sprig's hats are bought with (Fun, below). The footer (the
  version) sits at the foot of the sticky column, so at the window's foot however long the page; in a window too
  short for the rest, the part above it scrolls on its own. The room left between the blocks and the footer is
  Sprig's (Fun, below).
- **Narrower than `lg`, the rail is a strip** (`useRailMode`), since half of a second monitor is under it and a whole
  rail there left a list too little room: 3.5rem of the nav's icons (the nav's `compact`), each named on hover and to
  a screen reader, Attention's count one number on its icon's corner in its most severe item's color. A button atop
  the strip opens the whole rail, the same column, as a sheet over the page (`Sheet`, a Radix dialog: Escape or a click
  outside closes it, and the focus goes back to the button). It opens in its search box, so `/` opens it too. A link
  followed or a search sent from it closes it, since the page it covered is leaving. The breakpoint is the viewport's,
  as the rail's place is the window's; what a list shows is its own width's (Primitives, `ListRow`). Half a monitor,
  about 820px, is the narrowest window the UI is made for; a phone's is not.
- **Sizes are in rem, and rem grows with the window**: the browser's size up to a 1600px window, rising to a quarter
  larger at 2560px (`font-size` on `html` in `src/index.css`). Write sizes in rem (Tailwind's scale) so a large
  screen scales them; px only for hairlines and the like. Breakpoints are not scaled.
- **Wide screens use the width** from `2xl`: the attention list widens, and a detail page with a thread (below) puts
  it beside the rest, a ticket's conversation beside its work, runs, and decisions, a chore's notes beside its
  schedule, findings, runs, and spend. The source keeps the narrow order, which is the reading order; the grid only
  places the thread in a second column (`2xl:col-start-2 2xl:row-span-N`), over rows whose last is `1fr`, so a long
  thread leaves no gaps between the panels beside it.
- Between the header's name and its readouts, the ticker crawls joke headlines (Fun, below).
- The header carries the loop's pause (`LoopPause`), the latest tick (`tick:12 · 3m ago`, its status when not `ok`, in
  `status-failed` when it failed or was abandoned, its summary on hover, linking to its page), the stream's state (and
  `mock`), and the theme toggle, in three groups with a hairline rule between each: the pause, the readouts, the theme.
  The readouts hug their text, inset as far as a ghost button's label, so each rule sits midway. The counters are the
  attention page's, and the nav's Attention item shows how many items it lists, on every page, split by severity as the
  Attention counter splits them: broken in `status-failed`, waiting on the operator's answer in `status-blocked`, the
  rest muted, each only when there is one. Never in the section's rose, too near the failure color to tell apart at that
  size. Since color alone tells the numbers apart, they are said in words on hover and to a screen reader
  (`1 broken, 1 waiting on you, 3 other`), the words the Attention counter's line says under its value: one function
  splits the count for both (`breakdown` in `src/lib/attention.ts`).
- **The pause** is the header's standing action, since it is about the loop, not a page's subject: a ghost Pause
  button while the loop runs; paused, `paused · 3m` in `status-blocked` (the loop waits on the operator; when and
  from where on hover) and a Resume button. The button keeps one width in both states. It has no `Notice`: what it
  did is the state it shows, which the stream also sends when the loop's terminal or the CLI pauses. A failure colors
  the button `status-failed`, with the reason on hover and in an `sr-only` alert.
- **The notice to workers** (`NoticeBanner`, `canopy notice`) heads the content column, above every page, only while
  one is in force: a band on a `status-blocked` tint with its border, since every run waits on what the operator said,
  the notice's words through `LinkedText`, until when runs hear it (when and from where on hover), and a ghost Clear.
  It is not in the header, which has no room for a sentence, and it leaves with the stream's word when it lapses.
  Settings sets one, in its own panel, with how long it lasts as a toggle group; any other duration is the CLI's.
- **Reload** stands before the pause only while the server serves a newer build of the UI than the page loaded
  (`NewerBuild`): an accent button, the action to take, saying on hover why and that unsent text is lost. It never
  reloads on its own, since the operator may be typing. The page knows its build from the `canopy-build` meta tag the
  server writes into index.html, and the server's from `GET /api/meta`, read again whenever the stream comes back:
  a loop restarted on an upgrade drops it.
- Pages are a `PageHeader` followed by `Panel`s (`src/components/panel.tsx`). A panel's title row is `PanelHeader`,
  on `surface-raised` at half strength with its label in `foreground` at weight 500, so it stands apart from the rows
  under it; half, so a ghost button's hover in it still shows. In a panel too narrow for one line, what is on its
  right wraps under the label. The page header's trail starts in its section's color; a panel's label never takes
  one. A page's main list is named for its page's noun (Reviews on
  Reviews, Attention on Attention), and a chore's notes are Notes.
  Its title wraps (`min-w-0 break-words`) inside an unbroken word, since it can be a ticket's title or a search's
  query: a pasted URL widened the page. Its description is `text-balance` up to `max-w-3xl`: most fit on one line on
  a wide screen, a longer one splits into even lines rather than leaving a word or two on its last, and a command in it
  (`code`) never breaks across lines.
- **A detail page has one skeleton**: what it is, then its thread or main content, then the lists that support it.
  First the identity panel, its subject's fields (a ticket's Work, a run's Run, a PR's Pull request, a chore's
  Schedule); its actions sit in that panel's foot, under a hairline, never in a panel of their own above the content.
  Then the thread the operator came to answer, with its form: a ticket's conversation and the reply, a chore's notes
  and the note form. A page with no thread has its main content there instead: a run's transcript, a chore run's
  findings and transcript, a tick's decisions, a review's findings and diff, a PR's reviews. Then the supporting
  lists: runs, decisions, spend. So on a half-width second monitor a ticket's reply is reached before its runs and
  decisions, and the attention detail, the other place a ticket is answered, reads in the same order: the item, the
  ticket's actions and any limit it is stuck at, then its conversation and the reply. An action over a whole list
  sits in that list's panel header, as a transcript's All open does: the worktrees' Read again heads their one Pools
  panel, a section per pool in it.
- **Every page header opens with its trail**, a breadcrumb (`nav` named Breadcrumb) in `panel-label` type: the
  section's name in its color, then the pages between it and this one. On the section's own list the name is plain
  text; on any page under it every step is a link and ends in a small chevron, pointing at the title. A page in no
  section (search, the 404) names itself there in the accent. A parent is a journal name, so it keeps its case
  (`chore:deps` on a chore run) and stays muted until hovered. The title is the trail's last step, so the trail never
  repeats it. The trail follows the URL, not the journal: a run's page is under Runs, not its ticket, which its panel
  links. What qualifies a page, `private` or `dry run`, is a `Chip` beside the title, never a word in the trail.
- **The tab** names the page too: `PageHeader` renders a `<title>` (`pageTitle` in `src/lib/page-title.ts`), which
  React puts ahead of `index.html`'s. A tab is narrow and cut from the right, so it leads with how many attention
  items block work, when any do, then the page's name, then `canopy`: `(3) ABC-102 Export reports as CSV · canopy`.
  The count leaves out what only waits on someone else, a PR's `needs_reviewer` or `ready_to_merge`, and chore
  findings, which report rather than block (`blocking` in `src/lib/attention.ts`): a count that never falls to zero
  while PRs sit in review would stop meaning anything. The name is the header's title when that is plain text, else
  its `tab`; the sign-in page's is `Sign in`.
- **The nav wears the sections' colors**: every item's icon in its own, and the active item's highlight a 16% tint
  with a 2px hairline in it. In a page, **selected is the accent's tint**: the selected inbox row (`bg-accent/14`) and
  the runs page's chosen filter (`bg-accent/16`). Hover stays `surface-raised`, so selected and hovered differ.
- **The aurora**: a 2px hairline along the header's foot, over its border, fading from Attention's rose through Runs'
  violet to Worktrees' teal. It is static.

## Fun

canopy should be a little fun to use (PRODUCT.md), and the fun lives in a few named places, each written here, never
journal text: the ticker, Sprig, and the empty inbox. They share these rules:

- **Fun never covers data, and never squeezes it.** Each has a place of its own in the layout. Where the window
  leaves it too little room to be read, it steps out entirely, rather than shrinking, clipping, or sitting on
  something; its room stays, so nothing beside it moves. The fit is measured as the layout changes (`useFits` in
  `src/hooks/use-fits.ts`), before the first paint, so what does not fit never flashes in.
- **Fun is never colored as state.** Its colors are its own tokens (`flair-*`, `buddy-*`) or the accent, never a
  status color, so nothing in it reads as a run's state.
- **Fun honours reduced motion** (Motion, below): it holds still, and says the same.
- **Settings has one Fun panel**, second to last, below the settings that change how canopy works and above Session:
  an on/off for each, as checkboxes, then each one's details. Everything in it is kept in this browser (Themes, below).

The ticker:

- Between the header's name and its readouts, the ticker crawls joke headlines about programming and vibe coding,
  one at a time (`Ticker`, the headlines in `src/lib/headlines.ts`), in `text-xs` `muted-foreground`, faded out at
  both ends. Tips for using canopy are mixed in among the jokes, each opening with "Tip:" and without flair. Each
  headline is picked at random from the topics turned on, never the one just shown, so a topic turns up as often as
  its share of the headlines. A tip names a real key, command, or setting, in that command's own words; one that
  stops being true is fixed or dropped. A new topic is a name in `TICKER_TOPICS`, its headlines, and its label in
  Settings.
- It is on by default. Settings sets its speed (Slow, Normal, Spicy), the seconds between headlines (0 by default),
  and its topics (Programming, Vibe coding, Tips), a checkbox each, all on by default. Off keeps the rest for when it
  comes back on. With every topic off the window is gone, as with the ticker off.
- Its window is the room the header leaves between its name and its readouts. Narrower than 16rem, too narrow to read
  a few words of a headline in, the window is gone (`MIN_WIDTH_REM` in `src/components/shell/ticker.tsx`).
- A headline may open with RuneScape chat flair, typed as a player would: a color (`yellow`, `red`, `green`, `cyan`,
  `purple`, `white`, `flash1` to `flash3`, `glow1` to `glow3`), then an effect (`wave`, `wave2`, `shake`), each
  ending in a colon: `flash2:wave:Now with...`. Colors come from the `flair-*` tokens, never a status color, so no
  headline reads as a state. A flash swaps its two colors about once a second; an effect moves each letter a fraction
  of an em, and the headline is read once, as text, by a screen reader. Give flair to some headlines, not most.

Sprig:

- Sprig (`Buddy`, `src/components/shell/buddy.tsx`) is a bent wire with a sprig on top and googly eyes, behind a
  keyboard it vibe codes on (`Keyboard`), at the foot of the side rail, under a speech bubble offering a tip about
  the page. The keyboard stands in front of the wire's foot, inside the figure's own box, so Sprig takes no more room
  for it. It is off until Settings turns it on. Its tips are by page (`TIPS` in `src/lib/buddy.ts`): a set for each
  nav section (`src/lib/sections.ts`, so a new section must get its own) and for the search page, then ones for
  anywhere. Every one is a joke, and none opens with "Tip:",
  which on the ticker names something real; a joke dressed as a tip opens with "Unhelpful tip:". The jokes come in
  several voices (the paperclip's "It looks like you're...", a false "Fun fact:", a "Hot take:", a diary entry, a
  haiku, a riddle), mixed in each list so that no voice follows itself. Clicking Sprig, or the bubble's Another tip,
  offers the next; the bubble closes with its button or after 20 seconds, and "Don't show me tips again" turns Sprig
  off.
- Its place is the rail's column, between the blocks and the footer: the room left there is its slot, and it stands
  at the slot's foot. A slot with room for Sprig and its bubble (with the mock's three working runs, a window about
  1100px tall) covers nothing. A laptop's window never leaves that much, and the operator would rather see Sprig
  standing over the spend a little than not at all: so a shorter slot, down to one that leaves Sprig over the foot of
  the spend by 40px, still shows it, the one exception to Fun's first rule. There the bubble would cover the runs
  working now, so a tip shows only when asked for, by a click on Sprig, and closes as any other. A slot shorter
  still leaves Sprig out. The bubble keeps its room once closed, so closing it never moves Sprig.
- **Sprig's hats** are bought at the foot of Settings' Fun panel (`HatShop` in `src/routes/settings.tsx`, the shop in
  `src/lib/hats.ts`, the drawings in `src/components/hat.tsx`). The wallet is `total_usd` from `GET /api/spend`,
  everything canopy has ever spent, less the price of each hat bought, so it fills as canopy works; nothing real is
  spent. The shop is folded under its wallet row, which stays in view, until its `Show hats` opens it (a
  `Disclosure`, closed on every visit). The hats bought and the one worn are kept in this browser. A hat bought goes on
  at once; one owned goes on and comes off with a click; there are no refunds. Each hat is drawn in Sprig's own units,
  its brim on the top of the wire and under the brows, in the `buddy-hat-*` tokens, and drawn after the leaf, which
  shows behind the crown like a feather. Hats are priced for an operator who spends about $2,000 a month, $50 to
  $25,000: the first inside a day, the last after about a year. A new hat is an id in `HatId`, a row in `HATS` (cheapest
  first), and its drawing.

The empty inbox, and an item clearing:

- With nothing listed, the attention page shows a small canopy swaying, a leaf drifting off it (`AllClear`), in the
  accent: the one drawing in a page made for its own sake.
- An item leaving the attention list leaves with a small reward rather than vanishing: its row stays where it was,
  fades, then folds shut, while one of the empty inbox's leaves tumbles off it, in 600ms (`Leaving` in
  `src/routes/attention.tsx`, the rows from `withLeaving` in `src/lib/leaving.ts`). Any item that clears gets it,
  whether the operator cleared it (a reply read, a finding dismissed, a limit granted) or its cause went on its own:
  either way, work cleared. The leaving row is only for the eye: no link, inert, and hidden from a screen reader,
  which hears the list's count change. It never fakes state: the item is already gone from the list and the counters.
  The last item to leave shows the empty inbox at once instead.

## Motion

Motion says something arrived or changed, and gives the page some life without asking for attention. It is short
(at most 700ms), eased out (`cubic-bezier(0.2, 0, 0, 1)`), and never loops on anything but the logo, a running run,
a skeleton, the empty inbox, the header's ticker, and Sprig's blink and typing. The keyframes and utilities are in
`src/index.css`.

- Route changes cross-fade in 160ms through the `<ViewTransition>` around the outlet. The old page stays until the
  new one is ready, because navigations run inside React transitions.
- A page's blocks rise in one after another (`stagger` on the page column), and so do the attention list's rows, the
  Working rows, and a conversation's bubbles. A row or bubble the stream adds later rises in on its own. A bubble pops
  (`[--enter:pop]`) from the corner nearest its side.
- Counter values are odometers (`RollingNumber`): each digit rolls to its new value, the units first, and rolls up from
  zero when the counter first shows. The value is in the text once, for screen readers and tests; the digits are
  drawn by CSS.
- The nav's highlight (its tint and hairline) is one element that slides to the active item, changing into that
  item's section color as it goes.
- The header's logo is alive: its dot breathes while the stream is live, an arc sweeps its ring while a tick runs, and
  a ripple leaves it when a new tick appears.
- The theme toggle reveals the new theme as a circle growing from the button, in 420ms, and its new icon spins in.
- The header's ticker crawls one headline right to left, from the window's right edge until it has left by the
  left, then leaves the window empty for the set gap before the next. Every headline moves at the same pace, set in
  rem a second (`SPEED_REM` in `src/lib/ticker-settings.ts`), and holds still under the pointer. A headline starts
  from the window's width as its pass begins and keeps it, so the readouts beside it changing width as a tick starts
  or ends never move it back or on. At rest the window is empty, between headlines.
- Skeletons shimmer: a light passes over them.
- With nothing listed, the attention page shows a small canopy swaying, a leaf drifting off it (`AllClear`, Fun
  below).
- An item leaving the attention list fades and folds shut as a leaf tumbles off it (Fun, above). Its fold is the one
  animation that fills forwards: the row is let go once it has played.
- Sprig's tip pops in a moment after a page arrives, its brows rise once with each new tip, its eyes blink now and
  then and look toward the pointer, and every 5 seconds it types a burst on its keyboard, each key it presses sinking
  and lighting in the accent for a moment.
- A toast rises in from below and fades out.
- Only `running` runs pulse.
- Every animation rests on the frame a still page shows (its last, or for a loop its first), so a screenshot with
  animations frozen is the page at rest.
- Everything above is off under `prefers-reduced-motion: reduce`: the theme swaps instantly, values and rows appear
  in place, pulses, ripples, and the drifting leaf are hidden, a cleared item is simply gone, the ticker shows its
  first headline in place, and Sprig's eyes and keys hold still. New motion goes inside a `prefers-reduced-motion:
  no-preference` block or a `motion-safe:` variant.

## No layout shift

- `scrollbar-gutter: stable` on what the page scrolls in (`page-scroll`), so a page that grows a scrollbar does not
  move.
- Async content gets its space before it arrives: a fixed width for readouts, a minimum height for panels.
- A skeleton (`PanelSkeleton`) shows only while there is no data at all. A refetch or a stream update keeps what is on
  screen.

## Themes

Light, dark, and system, stored in `localStorage` under `canopy-theme` (absent means system) and synced across tabs.
The blocking script in `index.html` sets the `dark` class, `color-scheme`, and `data-theme` on `<html>` before first
paint; `src/theme/store.ts` keeps them current afterwards. Change one, change both: `theme-script.test.ts` runs the
inline script and checks it against the store's key. Whether the ticker is on, its speed, gap, and hidden topics are
kept the same way, as JSON under `canopy-ticker` (`src/lib/ticker-settings.ts`), whether Sprig is on under
`canopy-buddy` (`src/lib/buddy.ts`), the key that sends a reply under `canopy-send-key`
(`src/lib/send-key.ts`), and each list's order under `canopy-list-order` (`src/lib/list-order.ts`), all synced across
tabs. The ticker keeps the topics left out, not those shown, so a topic added later shows until it is turned off.

## Primitives

Every list and detail page is built from the same few pieces, so a new page lines up with the others without anyone
measuring. A page that needs something they do not offer extends them here first; it never builds a row, a field
list, an empty state, or a skeleton by hand.

- **`ListRow`** (`src/components/rows.tsx`): a list's row, a CSS grid in its kind's columns (`ROW_COLUMNS` in
  `src/lib/rows.ts`). Each column is a named grid line and a width; every one is fixed but one free column, which
  takes the rest and cuts its text to fit, so every row of a list lines up whatever its cells hold. The free column
  never gets under 8rem: it holds the row's name, a ticket's title, which never vanishes.
  **A narrow list lets columns go**, in the order its kind gives them (a third entry in `ROW_COLUMNS`, 1 first), so it
  fits its panel wherever the panel sits: half a monitor, beside a ticket's thread. A column shows from the narrowest
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
  status, a decision's action. What sits under a row outside it, a tool call's body, is a **`RowGrid`** of the same
  kind with a `RowLine` in it. A new list is a new kind in `ROW_COLUMNS`, its columns written out there.
- **`Fields`** and **`Field`** (`src/components/fields.tsx`): a detail page's field list, an `8rem` label column and
  the values beside it, the label in `panel-label` type and the value in prose or, with `mono`, in monospace data.
  The rows sit on their first baseline, so a label stays level with the first line of a value that wraps (a summary,
  a list of reviews), and a label that wraps does too. A total cost is a `Field` (`CostTotalRow`).
- **`ReviewsTable`** and **`RunsTable`**: review runs and runs, one row each, on every page that lists them. On the
  page of what they belong to, the columns that would repeat it go (`pr={false}`, `ticket={false}`), as a `ListRow`
  kind of their own (`own-review`, `own-run`).
- **`Empty`** (`src/components/panel.tsx`): what a list or page says when it has nothing to show, in muted text, in two
  sizes: `row`, where a panel's list would be, as its one row; `panel`, a page's main panel, centered with room
  around it. Its words are `no X yet` and one clause on why or what to do (`no runs yet: the overseer starts one when
  it is due`); `now` for what comes and goes rather than `yet` (`no open findings now`). A search that finds nothing
  says so; a page whose subject is missing says why. An error is never an `Empty`, and never a red sentence in a
  panel: it is a `Notice`, which names a refusal's guard.
- **`None`** (`src/components/none.tsx`): what a field or a cell holds when it has no value, `none` in muted text in
  its place's own type, never a sentence of its own. With a reason, the reason follows a colon; in a column too narrow
  for it (`brief`), the reason is on hover. One phrase per concept: a summary, a branch, a PR, a session, or a tick's
  output that was never recorded is `none`; a PR canopy only reviews has as its ticket `none: canopy only reviews it`
  (`NO_TICKET` in `src/lib/words.ts`). A list with no rows is an `Empty`, not a `None`.
- **`Input`**, **`Textarea`**, and **`SearchField`** (`src/components/input.tsx`): every text field, on
  `surface-raised` with a hairline and the accent's focus ring. An `Input` is one height everywhere, `h-9`, a form's,
  beside its default buttons; a number is an `Input` too. A field to search or filter with is a `SearchField`: a
  magnifier, the field, what it says at its end (a count), and a ghost clear button while it holds text, in the place of
  what sits there empty (the rail's keycap). Its two sizes are the rail's and a list filter's (`h-8`, `text-sm`) and a
  panel's own line of data (`sm`, `h-7`, `text-xs`). No page builds a field by hand.
- **`PanelSkeleton`** (`src/components/panel.tsx`): what a panel shows while its data has not arrived at all, `rows`
  shimmering bars, each shorter than the last. It takes the minimum height its content will (`min-h-72` for a page's
  main panel), so nothing moves when the data lands.

## Patterns

- **Lists are rows in a panel** (`ListRow`), divided by hairlines: a key column (a ticket key, a state), then the
  text in the free column, then readouts (cost, age) right-aligned, each as Readouts (below) says.
- **Readouts** say an age, a moment, or a cost one way on every page (`src/components/age.tsx`, `timestamp.tsx`,
  `cost.tsx`). An age is `Age`, the CLI's largest whole unit with the local time on hover, in the variant for what it
  measures: `ago` for a moment (`3m ago`: a message, a decision, a search hit, a ticket's or PR's last activity),
  `span` for something that runs (`for 3m`, then `ended 3m ago`: a run, a review, a tick, a chore run, a held
  worktree), and `bare` for how long an item has stood open, where its place says so (`3m`: an attention item, an open
  finding, the rail's runs, the oldest question). The header's tick is the one exception: `3m ago` once it ended, so
  its line stays short. A moment shown whole is `Timestamp`, the local `Oct 8 10:30` with the ISO time the journal
  keeps on hover, beside its age on a run's, tick's, chore run's, or review's page; a raw ISO string is never shown. A
  cost is `Cost`: `$0.42` as a readout, its dollars grouped by thousands (`$1,234.50`, `costText`, rounded to the cent
  as the CLI rounds), or a dash when nothing reported one, `none reported` on hover; never formatted in place, a hat's
  price included.
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
- **The runs page is a row per ticket** (`TicketRunsTable`, `byTicket` in `src/lib/run-state.ts`): the ticket's latest
  run, which says where it stands, and under it `Show N earlier runs`, a `Disclosure` that opens the runs before it,
  newest first, each one line in the row's own columns (a `ListRow` of the same kind): its state, the first line of
  what it said in muted text where the title is, its id and chips, cost, and when; the rest is on its run's page. The
  head line leads with the ticket: the state, the key, and the title in the free column, then the run's id and chips.
  What goes under it starts under the title. A ticket that asked, got its answer, and asked again is one blocked row,
  not two. The state
  filter goes by each ticket's latest run, and so do the rail's working runs and the Running counter's
  `N waiting on you`: a blocked run a later one followed waits on nothing. A ticket's page lists its runs flat
  (`RunsTable`), since every row there is the same ticket's. A run's line of links names its first three worktrees,
  then `+N more worktrees` with every one on hover, never `+1 more`, which would take the room the fourth's path
  does: a ticket across many repositories holds a slot in each, and its run's page lists them all.
- **A total cost** (`CostTotalRow`) is the last row of a ticket's Work panel and a PR's Pull request panel: the total
  as a `readout` (`costText`, a dash when nothing reported one), then, muted, what it counted
  (`over 3 runs and 1 review, 1 unpriced`; `countedText`), since the page lists only the recent ones.
- **The tickets list**: the key, the title in the free column, the `public` or `private, started` chip, the phase (cut
  to fit, the whole on hover), the running run or `waiting on you`, and the age. Narrow, the phase goes first, then
  the chip, then the age; the run, which says when the ticket waits on the operator, goes last. A run's list lets its
  cost go first, then its age, then its id and chips; a review's its cost, its impact, its ticket, its age, then its
  verdict; a PR's its working run, its age, then its review. Each kind's order is in `ROW_COLUMNS`.
- **The tickets filters** narrow the list two ways at once (`src/lib/ticket-filter.ts`). Where a ticket stands is the
  runs page's chips, in the Tickets panel's header (`?show=`): `open` (not done), `working` (a run on it now) and
  `waiting on you` (a question waiting), each with its run's dot, `blocked` (the overseer's phase for a ticket an
  open blocker ticket holds up, LOOP §7; no dot, since no run of it asked anything), and `done`. Under the header, a
  search field (`SearchField`, `?q=`) keeps the tickets whose key or title holds every word, in any case: the search
  page does not read titles, and in a list of a hundred tickets the operator knows the one by a word of its name. The
  list narrows as they type, each keystroke replacing the history entry, so Back leaves the page. A filtered count says
  `6 of 41`, and an empty result says which filter left nothing. Both filter the list the server sends, its 200
  newest by activity, not the whole journal.
- **Chips** (`Chip`) label a row with a fixed word: a kind, `private`, a reason. Never with journal text. A word
  the journal stores (a reason, an action, a kind, a phase) goes in as `word` and reads as words: underscores become
  spaces and an action's prefix takes a space after its colon (`worker failed`, `attention: needs reviewer`), while
  the CLI's spelling stays on hover, so it can still be found in `attention.md` or typed into the CLI
  (`src/lib/words.ts`). Outside a chip, a phase in a field or a list and a status in a header or a row read the same
  way (`Word`, `phaseLabel`); no journal word shows with its underscores. Journal text that is not a fixed word (a
  chore finding's id, `review.query`) and a count (`1 finding`) are muted monospace, never a chip. A chip with a
  long word in a narrow column cuts it to fit (`min-w-0 shrink`), as the search page's labels do; none is stretched
  to its column. Its color is its `tone`, from the one map of them (`Chip` in `src/components/status.tsx`): its color's
  hairline at 40% over the same color at 10%, so it holds its edge on a selected row's tint; `plain` in
  `muted-foreground`, else the status color of the state it marks, `failed`, `blocked`, or `running`. No chip is
  colored by classes of its own.
- **A status in a detail page's header** (a run's, a chore run's, a review's, a tick's) is a dot in its state's color
  and its word in that color. A run's journal says `done` where a tick's and a chore run's say `ok`: each is the CLI's
  word for its own, kept as it prints it, and both wear `status-done`, as a tick's `skipped` does (`tickState` in
  `src/lib/ticks.ts`).
- **A run state named in words** (a filter's chip, a counter's line) is the operator's: `blocked`, a run that asked,
  reads `waiting on you` (`RUN_WORD` in `src/lib/run-state.ts`), as the rail, the tickets list, and a question's chip
  say it. The URL keeps `?state=blocked`, and a run's own status in its page's header stays the CLI's word.
- **A ticket's title** (`TicketTitle`) follows its key, in medium weight, so it reads as the row's name and apart
  from what a run said under it; one line, cut to fit, the whole on hover. A ticket with none yet reads `untitled`,
  muted, so its cell is never blank, the rail's working runs included, never the run's kind in its place. A ticket's
  page heading sets the key in muted mono before it. Nowhere too narrow to show more than a few letters of it.
- **Counters** (`Counter`, `src/components/counter.tsx`) head the attention page (running, waiting on you, and
  attention; the spend is in the rail) and the worktrees page (working, held, needs a look, free, across every pool).
  The line under the value is cut to fit, and whole on hover, since it grows with the workspace (`4 pools unread`).
  Each is a label, the value, and one line under it, with a 2px top rule in the state color it counts:
  `status-running`, `status-stopped` for held, `status-blocked`, `status-failed` while something is broken. The
  same color washes down from the rule at 12%, fading out by 70% of the counter's height; a plain counter has none.
- **The spend chart** (the spend page): a bar per UTC day, the series stacked bottom up in `SERIES` order, idle
  overseer spend on the baseline so it compares across days, each segment as tall as its share of the dearest day.
  A bar says its day and each series' cost on hover. The chart is `aria-hidden`: the table under it, newest day first,
  holds the same numbers for a screen reader, each a `Cost`, and scrolls past a week (`PanelScroll`). A week names
  every day on the axis; 30 days every fifth, back from today. The window is a segmented control (`ToggleGroup`) in
  the totals' panel header, kept in `?days=`.
- **A slot strip** in a pool's header: one 10px square per slot, in slot order, in the worktree state's color, an
  idle one hollow. The counts beside it say the same in words, so the strip is `aria-hidden`. A pool of many slots
  wraps its squares onto more lines, sharing the header's room with the pool's root, never past the panel's edge.
- **A slot is one line** in our state words, never treehouse's (its word is on hover, as the path is on the slot's
  number). An idle slot shows its state and number alone, muted; only a note or an unreadable branch takes a second
  line, from the holder's column. The branch and the processes treehouse found share the free column, each cut to fit
  with the whole on hover: an agent can start a dozen, and the line still ends at the age. A pool treehouse could not
  read says why as a `Notice`.
- **Idle slots fold**: three or more in a row (`IDLE_RUN`, `slotGroups` in `src/lib/worktree-state.ts`) are one line,
  their state and then `Show 37 slots, #4 to #40`, a `Disclosure` (as a ticket's earlier runs are) that opens each
  slot's own line under it. A pool of many slots is mostly idle ones, which say nothing but their number; folded, those
  with work in them stay in reach. One or two in a row show as they are, since a toggle would save no room.
- **The worktrees filter** is the runs page's, by worktree state, in the Pools panel's header before Read again:
  `?state=` keeps the slots in that state and the pools with one (`poolShown`), under `broken` the pools treehouse
  could not read too, since Needs a look counts them. A pool's header still counts all its slots. Idle slots fold as
  they lie in the whole pool, so a filtered line never spans a slot in another state.
- **The attention list is an inbox**: one list, most severe first, beside the selected item. Severity
  (`src/lib/attention.ts`): broken work first (a run's `crashed`, `unpushed`, `unknown_result`, `worker_failed`,
  `attempt_limit`, `chore_failed`, and the review reasons), then what waits on the operator's answer (`awaiting_reply`,
  `untrusted_review`), then every other reason, then chores' findings; within each, the item open longest first. A
  row reads as an inbox's: its reason, subject, and age, then its ticket's title (`TicketTitle`, semibold) when it is
  about a ticket, as a message's subject, then its detail, muted, as the preview; the selected item's head puts the
  title, semibold, after the key. A
  reason chip takes `status-failed` or `status-blocked` for the first two, plain otherwise. A finding's reason is its
  id, the agent's text, so its chip says `finding` and the id follows its chore in muted monospace. An item's detail
  is the harness's line, with its `code` spans set as code and nothing else read (`InlineCode`), but for a GitHub PR's
  address, which is a `PullRequestLink` (its name alone in a row, which is a link already), so a detail names a PR as
  the rest of the page does. The harness names a run in it as `canopy show` reads one, `run:40`. The list is
  Attention, as the page and its counter are; what waits on the operator's answer is `waiting on you` wherever it
  shows: the counter, a question's chip in a conversation, the tickets list, and the rail. The selection is
  `?item=<id>`; with none, the most severe item about a ticket. A ticket's item shows, under the item, the ticket's
  actions and what it is stuck at (below), then its conversation and the reply form, as a ticket's page orders them;
  an item about a PR no ticket owns, its review limit; a chore's item (a finding or `chore_failed`) shows the chore's
  notes and the note form, and a finding a ghost `dismiss` beside its age (`useDismissFinding`) and, in place of its
  detail, the finding as its chore's page has it (`ChoreFindingText`): the title whole, then what it says of itself,
  then its link on its own line, where the item's detail runs title and link together; an item about neither
  shows its detail and nothing to answer. The page keeps no list of the runs working now: the rail's, on every page,
  is the one, so one count of them shows at a time.
- **A conversation** is a column of messages, each a head line (id, who, kind, age) over a bubble at most `max-w-2xl`
  wide: `surface-raised` for a worker's report or a tracker comment, the `status-blocked` tint for a question, and the
  accent's tint for the operator's own words, which sit on the right. A bubble's corner nearest its side is square.
  The question still open carries a `waiting on you` chip in `status-blocked`.
  Bodies keep their line breaks (`whitespace-pre-wrap`) and are always text, but for their URLs (below). An operator
  message no `ok` tick has read carries a `waiting for the next tick` chip in `status-running`
  (`src/lib/acknowledged.ts`), and an `awaiting_reply` item it answered an `answered` chip, with a line saying it leaves
  at the next tick; Waiting on you counts neither. While a run works the ticket, the conversation ends on it (starts on
  it, flipped newest first), on the worker's side, as a chat shows someone typing (`WorkingNow`): a pulsing `RunDot`,
  `working now` in `status-running`, its `run:N` link, its kind, its latest tool call (`RunDoing`, below), its cost
  so far, and for how long. It comes from the runs on the stream, so it rises in when the run starts, follows what it
  does, and leaves when it ends.
- **A running run's latest tool call** (`RunDoing`, `src/components/run-doing.tsx`): one line of mono data, the tool
  in `status-running`, what the call did muted (a shell call's command, else the runtime's title; cut to fit, whole on
  hover), and how long ago. A running run's row has it where an ended run's summary goes, `WorkingNow` after the
  kind, and the run's page as its `last call` field. It is agent output, rendered as text.
- **A URL in journal text** (`LinkedText`): an http or https URL in a message body, a summary, a rationale, or a
  detail is a link in `accent`, underlined so it reads as one inside prose, its text the URL as written; it opens in a
  new tab. A PR shown in its own place (a run's or decision's PR) is a `PullRequestLink` (below), and so is a GitHub
  PR's address in a conversation's bubble or a chore's finding, its detail or its link, as in the harness's lines
  (`InlineCode`).
- **A chore's notes** are a conversation of the operator's words alone, between the chore's schedule and its findings
  and runs, with a note form (`ChoreNotes`). A note no run of the chore has started since carries `waiting for the
  next run` in `status-running` (`src/lib/chores.ts`): no tick reads a note, so the tick chip would be wrong there.
- **Decisions** are rows (`Decisions`): the subject, a ticket or chore as a link, a unit as its ticket and repository
  (on its subject's page, the tick instead, with its age), the action as a chip, a PR as a link, and the rationale
  under them as rich text, from the action's column. A `refused:` action's chip is in `status-failed` and an
  `attention:` one's in `status-blocked` (`src/lib/decisions.ts`); the rest are plain. A tick in a list is its id as a
  link, its status in the header's tick colors (`src/lib/ticks.ts`), how many decisions, its cost, and when it ended.
- **A transcript** (`TranscriptPanel`) is a session's events as rows, in the order the runtime printed them, each with
  its time from the session's first event (`+12:05`; the local time on hover). The agent's text keeps its line breaks,
  its reasoning muted and italic under a `thinking` label. A tool call is a native `<details>` whose line says what it
  did and how it ended (`src/lib/transcript.ts`): a `RunDot` in `done` or `failed`, the tool's name, and in monospace a
  shell call's command (the agent's description of it on hover), else the runtime's title, else its input's short values
  as `key=value`; under that, muted, its error's first line in `status-failed`, or an output of one short line that is
  not JSON; then how long it took. A canopy command that printed a refusal is `failed`, with a `refused: <guard>` chip
  in `status-failed`. It opens to its input and its output (or error), JSON indented and colored as a tick's output is
  with Pretty on (below), every value as written, in monospace blocks at most 24rem tall. A model call is a muted line
  with its tokens and cost, and its reason only when it is not `tool-calls`, as every call but the last is; it opens the
  same way to its tokens by kind, each a label and a readout on one line, and All open leaves it closed. A runtime error
  is tinted `status-failed`. The header has the session id, then a hairline rule and the modes: the order, By call, and
  All open, a `Toggle` that opens every call turned on and closes them all turned off, and is on too while a search has
  opened what it found. Above the rows, how many tool calls, failed and refused ones, and model calls, and at that
  line's end a search field (`Find lines`, `SearchField` at its `sm` size). A search keeps only the rows with a line
  that holds it, letters in either case and every character taken literally, and says how many lines and rows that is in
  the field; its matches are marked on the accent's tint as the search page's are (`MarkedText`), inside a block's
  colored JSON too (`markedTokens`). A tool call whose input or output holds it opens to it, until All open is turned on
  or off; a model call is numbers alone and is never kept. Escape or the clear button empties it, and a search nothing
  matches says so in place of the rows. A By call `Toggle` in the header, as Pretty is, groups the rows by the model
  call they came from (`byCall` in `src/lib/transcript.ts`), hiding the search, which is the rows' in order: each call a
  `Collapsible` row, its number, what it did (its first text, then its tools by name, `read ×2`), an `unfinished` chip
  when the session ended first, its reason as above, its tokens `in · out`, and its cost. It opens to an input and an
  output section, each a `panel-label` with its tokens: the first call's input is the prompt canopy kept, in a block,
  with a muted line saying what no file records; a later call's is each tool its predecessor called, a `RunDot`, the
  tool, and its summary over its output's block. The output is the call's rows as above, in a bordered list. A call's
  body is built only when opened, and All open opens the calls. A run's id in a list (`run:N`) opens its page, which is
  the run's fields over its transcript, and a chore run's id (`chore:NAME#N`) its page, whose findings sit between the
  two; a tick's page has the overseer's under its decisions.
- **A tick's output** (`TickOutputPanel`) is the overseer's file as written, under the tick's transcript: one muted line
  naming the file until `Show output`, a `Disclosure` in the header, opens it. Open, it is one monospace block, its
  lines wrapped anywhere (JSON events have no spaces to break at), scrolling inside the panel (`PanelScroll`) and opened
  at its end, where stderr is; the file's size is in the header, and a cut says so above the block. A line that parses
  as a JSON object or array (the runtime's events) is colored as written, never reformatted (`src/lib/json-lines.ts`,
  `JsonTokens`): keys, strings, numbers, and literals in the `syntax-*` tokens, punctuation muted; any other line stays
  plain. A transcript's block is colored the same way when the whole of it is JSON. A Pretty `Toggle` in the header (a
  mode, raised while on) lays each JSON line out over several, two spaces a level, by the space between its tokens
  alone, so every value stays as written; it reopens the block at its end. Each tick's panel keeps its own choice, off
  until turned on, across reloads (`src/lib/pretty-output.ts`), as a list keeps its order.
- **Rich text** (`RichText`, `src/lib/rich-text.ts`) lays out what an agent wrote, a run's, chore run's, or tick's
  summary and a decision's rationale: line breaks kept, `-` and `1.` lists (nested by indent), `#` headings as a
  `font-medium` line, fenced code as a `surface-raised` block that scrolls sideways, and `code` (at `text-xs`) and
  **strong** inline.
  It reads nothing else: other markup, a labelled link's included, stays characters. Every piece is React text, and
  its text and strong pieces go through `LinkedText`, so a URL outside code is a link to itself. In a list's row it
  shows the first four lines and a `show N more lines` toggle in the accent; text one line over shows whole.
  A conversation's bubbles keep their own `whitespace-pre-wrap`.
- **A plan in its editor** (`PlanEditor`, `src/components/plan-editor.tsx`; docs/design/PLANNING.md §25): the plan in a
  `Plan` panel, its toolbar in the panel's header, and the comments in a `Comments` panel beside it from `2xl`, under it
  below that, as a thread sits beside a ticket's work. The plan is laid out as a document (`.plan-doc` in
  `src/index.css`): `text-sm` prose up to `max-w-3xl`, headings at `text-xl`, `text-base`, and `text-sm` semibold, code
  as rich text sets it, a table in hairlines with its header row on `surface-raised` at half, a quote muted behind a
  hairline. What the plan holds as characters (HTML, an image) is muted monospace; a link is underlined in
  `muted-foreground` with its address on hover, never a link. The toolbar (`Toolbar`, below) is `icon-xs` toggles in
  groups split by hairlines: undo and redo, the paragraph's style (a choice of one), the marks and the blocks (each on
  or off, raised while on at the cursor), then `Comment`, enabled while text is selected. Each control's tooltip names
  it and the shortcut the editor binds to it, on this keyboard (`Bold (⌘B)`, `Bold (Ctrl+B)` elsewhere), and declares
  the same keys as `aria-keyshortcuts`. A selection also shows a `Comment` bubble over it. A commented passage sits on
  the accent's tint at 14%; the open one, or the one being commented on, at 28% and underlined in the accent; clicking a
  passage opens its thread, and the cursor leaving it, or Escape, closes it. A thread is its passage quoted (two lines,
  a hairline in the accent at its left, the whole on hover; a button that shows it in the plan), the comment and its
  replies as text with their ages, and ghost `xs` actions, `Reply`, `Resolve` (`Reopen`), and `Delete`; the open thread
  sits on the accent's tint, as a selected row does. A thread whose passage is gone carries a `passage gone` chip and
  stays in the list, last. Resolved threads fold under a `Disclosure` (`Show 2 resolved`). A comment or reply form sends
  on the key Settings names, as a reply does, and Escape drops it. A form takes the cursor when it opens, after any
  words it holds. `Comment` again, on new words, moves an empty comment to them; one half written stays on its passage,
  and the cursor goes back to it, so its words are never lost or carried to other words. The comments end in
  `Ask for changes`: a note on the whole plan and the button, with how many open comments go with it, or how far over a
  reply's bound the request is. Until plans reach a ticket's page (M44), the editor is on `/plan-editor`, over a sample
  plan on mock data only, with what the planner would read and the plan's Markdown under it.
- **A chore** is a line in `canopy status`'s words (`choreLine`: `running for 10m`, `last ok 4h ago, due in 1h`) in
  its latest run's state color, then how often it may start and its window (`cadenceText`: `every 360 minutes`, as
  the config and the CLI say it; `windowText`), its open findings less those dismissed, then how many were dismissed
  as `canopy status` counts them (`findingsText`: `1 open finding · 2 dismissed`; its page's findings panel the
  same, `findingsReadout`: `1 · 2 dismissed`), and what its runs cost in the last
  24 hours and 30 days (`costText`, a dash when none reported a cost). Its page puts that spend in a table under its
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
  trails, titles, and the tab alike: `run:41`, `review:4`, `chore:deps`, and in the same grammar `tick:2`, which the
  CLI takes no reference for. A chore run has no reference of its own, so it is its chore's and its number,
  `chore:deps#2`, as GitHub writes an issue's. Each has a link component that opens its page (`RunLink`, `TickLink`,
  `ReviewLink`, `ChoreLink`, `ChoreRunLink`), used wherever it is named, a message's head and a worktree's holder
  included; a page's title calls the same function. A message is `#5`, as its conversation numbers it, and a worktree
  slot `#3`, as treehouse does (`messageRef`, `slotRef`). Nothing builds a reference in place. A PR is named as
  GitHub writes a reference, `org/repo#123` (`pullRequestLabel`; any other host's URL as written without
  `https://`), and only through `PullRequestLink`.
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
- **Text to paste elsewhere** has a copy button after it (`Copyable`, `CopyButton`): a branch on a ticket's, run's,
  or PR's page, a run's worktrees and log path, a session id wherever one shows (a tick's page, a transcript's header,
  a run's row, a chore run's row), and a review's commit, whole though the page shows its first 7 characters. A path
  copies whole though the page shows it from the workspace root (`CopyablePath`), joined to `/meta`'s root; until that
  is read there is no button, so a copy is never the short path. The button is a ghost `icon-xs` with the
  `Copy` icon, muted until hovered; a click shows `Check` in the accent, or `X` in `status-failed` when the browser
  refuses, for 1.5 seconds, and names what happened (`Copied branch`), and a toast says the same with the text it
  copied, on one line. In a dense list (a worktree slot's path and branch, a run's or chore run's session id) it shows
  only while its row (`group/copy`) is hovered or it has the focus, keeping its space so nothing moves, and always on
  a touch screen. The clipboard needs a secure context (https or localhost), so elsewhere there is no button and the
  text stays selectable.
- **A toast** (`Toaster`, `useToast` in `src/hooks/use-toast.ts`) says what an action did when the place it was
  done shows too little of it: a copy names what it copied. It sits at the bottom center of the window on `surface`
  with a hairline, a `Check` in the accent or an `X` in `status-failed`, its title in `text-sm`, and a line under it
  in muted monospace `text-xs`, on one line with an ellipsis where it is cut: what it names is on the clipboard,
  whole. It closes on its own after 3 seconds, held while the pointer or the focus is on it, or when swiped down; F8
  reaches it from the keyboard and Escape closes it. At most three show, the newest last. A screen reader announces
  it. It never carries an action, and it is never the only place an outcome shows: the control that acted says so
  too, and a refusal is still a `Notice`. `main.tsx` renders the one `Toaster`, around the router, so a toast
  outlives the page it came from.
- **A reply or note form** sends on the key Settings names: Enter by default, as a chat does; Ctrl+Enter (⌘+Enter on
  a Mac), Enter making a new line; or Button only. Shift+Enter always starts a new line, and an Enter that ends an IME
  composition only commits it (`src/lib/send-key.ts`). Its field is named for the form, as its panel is for its page:
  `Reply`, `Note`, or `Reply to message 5` while a question waits. The send button names its key in a keycap (`Kbd`)
  after its label, in the accent foreground's tint: ⏎, or ⌘⏎ on an Apple keyboard and Ctrl⏎ elsewhere; Button only
  shows none. The keycap is `aria-hidden`; the button carries the same keys as `aria-keyshortcuts`.
- **Behavior comes from Radix**, through the shadcn wrappers in `src/components/ui/`, and only they import it (the lint
  refuses `radix-ui` anywhere else): a button that is on or off is a `Toggle`, a part of the page that opens under its
  button is a `Collapsible` (the panel or row itself, by `asChild`, so it adds no wrapper) opened by a `Disclosure`
  (below), an option that is on or off a `Checkbox`, a choice of a few options a `ToggleGroup`, and a row of an
  editor's controls a `Toolbar` (`src/components/ui/toolbar.tsx`), one tab stop with the arrow keys between them.
  Radix keeps their ARIA in step with their state (`aria-pressed`, `aria-expanded` with `aria-controls`), so a
  component never writes it by hand. Two stay native on purpose: a transcript's tool call is a `<details>` (above),
  and rich text's `show N more lines` shows more of text already on screen rather than opening a part, so it is a
  plain button with `aria-expanded`.
  A new wrapper is shadcn's, added or ported as `button.tsx` was.
- **Modes and disclosures** follow one rule each, so a control says which it is before it is clicked:
  - A **mode**, a way of showing what is already there, is a pressed `Toggle`, a ghost `xs` button raised while on,
    labelled with the mode and never with what a click does: Pretty, By call, a transcript's All open. It names the
    mode in both states; `aria-pressed` says which. A list's order, which has two values and no off, is the one
    exception (`OrderToggle`): it names the order in force (`newest first`), the arrow saying it flips.
  - A **disclosure**, what opens a part of the page under it, is a `Disclosure` (`src/components/disclosure.tsx`) on
    its `Collapsible`: a ghost `xs` button, a chevron that turns down while open, and what it does in words,
    `Show <what>` closed and `Hide <what>` open (`Show output`, `Show 2 earlier runs`, `Show 37 slots, #4 to #40`,
    `Show hats`). In a row's line it sits in line with the text above it (`-ml-2`), no taller than a line (`-my-1`).
    A row that opens to its own body, a transcript's tool call or model call, is the row itself, a chevron at its end.
  - Two of either are one: a pair that does and undoes (Open all, Close all) is one `Toggle` (All open).
  - A panel header's modes sit together, after what the panel is about: a transcript's session id, a hairline rule,
    then its order, By call, and All open.
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
- **An action** is a button in the foot of its subject's identity panel (the detail skeleton, above) or under its
  form, with one line under it (`Notice`): what the action did, in the CLI's words, or its refusal in
  `status-failed`, naming the guard. An action that kills something asks
  once more inline (Stop now, then End run N now), never through a browser dialog. One that cannot be undone asks
  for its subject typed out: Forget opens a form in `status-failed` that says what it drops and keeps, and its button
  stays disabled until the field holds the ticket's key exactly.
- **A limit something is stuck at** (`GrantLimits`) sits under a ticket's actions, in its Work panel's foot on its
  page and under the item's head on its attention item, above the conversation either way, and in the foot of a PR's
  Pull request panel, under the operator's review request. While something is stuck it is a block on the
  `status-failed` tint, the color its `attempt_limit` chip wears, so it stands out from the panel: a line in body text
  led by `At its limit.` in `status-failed`, then a row per limit whose runs have reached it, what it counts in
  monospace (`fix-ci in web`, `reviews of web#88`), its runs against it in `status-failed` (`1 of 1 runs`, and `, N
  granted` past the policy's), and an outline `Allow one more` button at the row's end, as a ticket's actions are, the
  CLI's command on hover. What the grant did goes under the rows (`Notice`), untinted once nothing is stuck; the row
  leaves once the limit is above its runs. A limit with room left shows nothing.
- **A review request** (`ReviewRequestForm`, `ReviewRequestStatus`) is how the operator has canopy review a PR the loop
  does not own (DESIGN §21). The pull requests page leads with a `Review a PR` panel above the list: a line saying
  nothing is posted on the PR, the PR's URL in a monospace field, and a `Review` button beside it, the form's submit,
  with the CLI's command on hover. It takes no repository: the overseer finds the PR's (DESIGN §21). A PR with an open
  request wears a `requested` chip after its review in the list. On a PR's page the request is a line in the foot of its
  Pull request panel, since when, with an outline `Stop` at its end while it is open, or how it ended once it has; what
  Stop did goes under it (`Notice`).
- **A review** (`/reviews/$id`) is canopy's shadow PR review, kept in the journal and posted nowhere (D114): the
  review's fields, its findings as a list linking to each one's card, and the diff, a panel per file. A diff is a
  monospace table: the old and new line numbers, the `+` or `-` in `diff-add` or `diff-del`, and the line, its row on
  that token's 12% tint; a hunk's header on `surface-raised`; long lines scroll sideways inside the panel. A finding's
  card (`FindingCard`) sits right under the line it names, or under its file's header when the diff does not show the
  line, or in a Not in the diff panel: its number, its severity as a chip (`blocking` in `status-failed`, `major` in
  `status-blocked`, as the attention list's reasons; `minor` plain), its title, its location, and its detail as rich
  text, with `dismiss` at the end of its head line (`useDismissReviewFinding`); a dismissed one has a `dismissed` chip,
  its title muted, `undo` in place of `dismiss` (as on a chore's finding, and as `canopy dismiss --undo`), and the
  same chip in the findings list. On a review of one of the loop's own PRs (`sendable`), each finding in that list
  the operator has not dismissed has a checkbox before its number, and under the list `send to a worker` sends the
  ticked ones together, as `canopy send review:ID N...` does, with a muted line saying what it does until it has said
  what it did. The list of reviews is a `ReviewsTable`: the review's link, its run state's dot and its verdict in its
  worst finding's color (`verdictTone`: a blocking one's `status-failed`, a major one's
  `status-blocked`, else plain), so a review with a blocking finding never reads as calm as a clean one, and the worst
  in words, since color alone says nothing to some (`verdictText`: `3 findings, 1 major`, or `1 blocking finding` when
  every finding is that bad); its ticket
  (or `None`, its reason on hover), the PR (`PullRequestLink`), the commit's first 7 characters, its impact, cost,
  and age. A review's page colors its verdict the same way.
- **A PR** (`/pull-requests`, `/pull-requests/pr?url=`) has a section of its own. A PR's row: the PR (`PullRequestLink`,
  the URL on hover), its ticket and title (or `none: canopy only reviews it`, `None`) and its unit's phase as a chip in
  the free column, then the run working it now (a pulsing dot and `run:N`), its latest review (its state's dot,
  `review:N`, and its verdict, in its worst finding's color; `not reviewed` muted), and its age. Its page: the PR's name
  (`org/repo#123`) as the title with its phase as a chip, a link out under it as a ticket's page has (`LinkOutButton`),
  saying where it goes (`on GitHub`) rather than repeating the title, then panels for its fields and total cost, with a
  grant of another review in its foot when it is at its review limit, its reviews (`ReviewsTable`), the runs that pushed
  to it (`RunsTable`), and its decisions. The journal keeps no PR's own title, so the page has none to show.
- **Search** sits atop the nav on every page (`SearchBox`, a `SearchField`): a magnifier, the field, and `/` in a
  keycap, its shortcut from anywhere but a text field. While the field holds text, a ghost clear button (`X`, on the
  keycap's `bg-muted` when hovered) takes the keycap's place: it empties the field and keeps the focus there. An empty
  field, by the button or by deleting its text, empties the search page if it is open, and leaves any other page as it
  is. The search page has a panel per source with hits, in the server's order, its count in the header (`newest 20` when
  the source has more). A hit is a row: where it opens (its ticket or chore with the run that said it, a chore run as
  itself, `chore:deps#2` opening its page, or the tick that decided it), its label as a chip (a chore run's status as
  its dot and word, as its chore's page lists it), the snippet with the query's words marked on the accent's tint
  (`bg-accent/20`, `src/lib/search.ts`), and its age. A snippet links nothing, since it may cut a URL short. While the
  next query's hits load, the last ones stay, dimmed to 60%.
- **Signed out**, the whole page is the sign-in card, centered on the canvas: no shell, nothing from the journal.
