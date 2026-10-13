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
decoration, but the header ticker's flair. Both themes' neutrals carry the accent's indigo hue, so the canvas has
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
| `flair-yellow`, `-red`, `-green`, `-cyan`, `-blue`, `-purple` | The ticker's RuneScape chat colors, and only those. |

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
- **Section colors**, one per nav item: Attention rose, Runs violet, Worktrees teal, Tickets sky, Pull requests gold,
  Reviews fuchsia, Chores orange, Ticks lime, Settings lavender (`src/lib/sections.ts`; the current one from
  `useSection`). They go on the nav's icons and highlight, the first step of the page header's trail, and the header's
  aurora, and nowhere in a page's data: there a color is a state's. A page in no section (the 404) takes the accent.
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
- The shell: a 3rem header, a 13rem side nav, content capped at `max-w-[112rem]` with `p-6` and `gap-6` between
  blocks.
  The header stays put and only what is under it scrolls (`page-scroll`), so the header spans the window's width
  and a scrollbar, or the gutter kept for one, sits beside the rail and the page, never beside the header: the
  browser paints the window's own gutter with the canvas color alone, so when the window scrolled, the header
  stopped short of its edge. The side rail runs the full height of the page, and what it holds sticks: a column as
  tall as the window under the header. Printed, the shell is not held to the window and shows the page whole; a
  screenshot test does the same by growing the window to the page (`screenshotWhole` in `e2e/helpers.ts`).
- **The rail** holds, top to bottom: the search box, the nav, the runs working now, the spend, and a footer
  (`src/components/shell/rail.tsx`). Each nav item says on hover what its page holds, and each spend window what it
  covers, as a native `title`. Each block under the nav is a hairline and a `panel-label` over its content. The
  working runs are those running first, then those waiting on the operator's answer, each oldest first, a ticket's
  latest run alone: a dot in its state's color, the ticket's key, how long it has run (or `asks` in
  `status-blocked`), and the ticket's title under it, opening the run's page; at most four, then `+N more` to the
  runs page, so the sticky part fits an 800px window.
  The spend is the last 24 hours and the last 30 days from `GET /api/spend`, on the stream, in small readouts: it
  is shown nowhere else. The footer (the version) sits at the foot of the sticky column, so at the window's foot
  however long the page; in a window too short for the rest, the part above it scrolls on its own. Sprig, when on,
  stands just above the footer, never on it.
- **Sizes are in rem, and rem grows with the window**: the browser's size up to a 1600px window, rising to a quarter
  larger at 2560px (`font-size` on `html` in `src/index.css`). Write sizes in rem (Tailwind's scale) so a large
  screen scales them; px only for hairlines and the like. Breakpoints are not scaled.
- **Wide screens use the width** from `2xl`: the attention list widens, a ticket's page puts its conversation
  beside its actions, work, and runs, and a chore's page puts its notes beside its schedule, findings, and runs.
- Between the header's name and its readouts, a ticker crawls joke headlines about programming and vibe coding, one
  at a time (`Ticker`, the headlines in `src/lib/headlines.ts`), in `text-xs` `muted-foreground`, faded out at both
  ends. It is the header's one piece of fun: written here, never journal text. Tips for using canopy are mixed in
  among the jokes, each opening with "Tip:" and without flair. Each headline is picked at random from the topics
  turned on, never the one just shown, so a topic turns up as often as its share of the headlines. A tip names a
  real key, command, or setting, in that command's own words; one that stops being true is fixed or dropped.
  Settings sets its speed (Off, Slow, Normal, Spicy; Off hides it), the seconds between headlines (0 by default), and
  its topics (Programming, Vibe coding, Tips), a checkbox each, all on by default. With every topic off the window is
  gone, as with Off. A new topic is a name in `TICKER_TOPICS`, its headlines, and its label in Settings.
- A headline may open with RuneScape chat flair, typed as a player would: a color (`yellow`, `red`, `green`, `cyan`,
  `purple`, `white`, `flash1` to `flash3`, `glow1` to `glow3`), then an effect (`wave`, `wave2`, `shake`), each
  ending in a colon: `flash2:wave:Now with...`. Colors come from the `flair-*` tokens, never a status color, so no
  headline reads as a state. A flash swaps its two colors about once a second; an effect moves each letter a fraction
  of an em, and the headline is read once, as text, by a screen reader. Give flair to some headlines, not most.
- The header carries the loop's pause (`LoopPause`), the latest tick (`tick 12 · 3m ago`, its status when not `ok`, in
  `status-failed` when it failed or was abandoned, its summary on hover, linking to its page), the stream's state (and
  `mock`), and the theme toggle, in three groups with a hairline rule between each: the pause, the readouts, the theme.
  The readouts hug their text, inset as far as a ghost button's label, so each rule sits midway. The counters are the
  attention page's, and the nav's Attention item shows how many items it lists, on every page, split by severity as the
  Attention counter splits them: broken in `status-failed`, waiting on the operator's answer in `status-blocked`, the
  rest muted, each only when there is one. Never in the section's rose, too near the failure color to tell apart at that
  size.
- **The pause** is the one action in the header, since it is about the loop, not a page's subject: a ghost Pause
  button while the loop runs; paused, `paused · 3m` in `status-blocked` (the loop waits on the operator; when and
  from where on hover) and a Resume button. The button keeps one width in both states. It has no `Notice`: what it
  did is the state it shows, which the stream also sends when the loop's terminal or the CLI pauses. A failure colors
  the button `status-failed`, with the reason on hover and in an `sr-only` alert.
- Pages are a `PageHeader` followed by `Panel`s (`src/components/panel.tsx`). A panel's title row is `PanelHeader`,
  on `surface-raised` at half strength with its label in `foreground` at weight 500, so it stands apart from the rows
  under it; half, so a ghost button's hover in it still shows. The page header's trail starts in its section's color;
  a panel's label never takes one.
  Its title wraps (`min-w-0 break-words`) inside an unbroken word, since it can be a ticket's title or a search's
  query: a pasted URL widened the page. Its description is `text-balance` up to `max-w-3xl`: most fit on one line on
  a wide screen, a longer one splits into even lines rather than leaving a word or two on its last, and a command in it
  (`code`) never breaks across lines.
- **Every page header opens with its trail**, a breadcrumb (`nav` named Breadcrumb) in `panel-label` type: the
  section's name in its color, then the pages between it and this one. On the section's own list the name is plain
  text; on any page under it every step is a link and ends in a small chevron, pointing at the title. A page in no
  section (search, the 404) names itself there in the accent. A parent is a journal name, so it keeps its case
  (`chore:deps` on a chore run) and stays muted until hovered. The title is the trail's last step, so the trail never
  repeats it. The trail follows the URL, not the journal: a run's page is under Runs, not its ticket, which its panel
  links. What qualifies a page, `private` or `dry run`, is a `Chip` beside the title, never a word in the trail.
- **The tab** names the page too: `PageHeader` renders a `<title>` (`pageTitle` in `src/lib/page-title.ts`), which
  React puts ahead of `index.html`'s. A tab is narrow and cut from the right, so it leads with the attention list's
  count, when it holds anything, then the page's name, then `canopy`: `(3) ABC-102 Export reports as CSV · canopy`.
  The name is the header's title when that is plain text, else its `tab`; the sign-in page's is `Sign in`.
- **The nav wears the sections' colors**: every item's icon in its own, and the active item's highlight a 16% tint
  with a 2px hairline in it. In a page, **selected is the accent's tint**: the selected inbox row (`bg-accent/14`) and
  the runs page's chosen filter (`bg-accent/16`). Hover stays `surface-raised`, so selected and hovered differ.
- **The aurora**: a 2px hairline along the header's foot, over its border, fading from Attention's rose through Runs'
  violet to Worktrees' teal. It is static.

## Motion

Motion says something arrived or changed, and gives the page some life without asking for attention. It is short
(at most 700ms), eased out (`cubic-bezier(0.2, 0, 0, 1)`), and never loops on anything but the logo, a running run,
a skeleton, the empty inbox, and the header's ticker. The keyframes and utilities are in `src/index.css`.

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
  rem a second (`SPEED_REM` in `src/lib/ticker-settings.ts`), and holds still under the pointer. At rest the window is
  empty, between headlines.
- Skeletons shimmer: a light passes over them.
- With nothing listed, the attention page shows a small canopy swaying, a leaf drifting off it (`AllClear`). It is
  the one drawing made for its own sake, in the accent.
- Only `running` runs pulse.
- Every animation rests on the frame a still page shows (its last, or for a loop its first), so a screenshot with
  animations frozen is the page at rest.
- Everything above is off under `prefers-reduced-motion: reduce`: the theme swaps instantly, values and rows appear
  in place, pulses, ripples, and the drifting leaf are hidden, and the ticker shows its first headline in place. New
  motion goes inside a `prefers-reduced-motion: no-preference` block or a `motion-safe:` variant.

## No layout shift

- `scrollbar-gutter: stable` on what the page scrolls in (`page-scroll`), so a page that grows a scrollbar does not
  move.
- Async content gets its space before it arrives: a fixed width for readouts, a minimum height for panels.
- A skeleton (`Skeleton`) shows only while there is no data at all. A refetch or a stream update keeps what is on
  screen.

## Themes

Light, dark, and system, stored in `localStorage` under `canopy-theme` (absent means system) and synced across tabs.
The blocking script in `index.html` sets the `dark` class, `color-scheme`, and `data-theme` on `<html>` before first
paint; `src/theme/store.ts` keeps them current afterwards. Change one, change both: `theme-script.test.ts` runs the
inline script and checks it against the store's key. The ticker's speed, gap, and hidden topics are kept the same
way, as JSON under `canopy-ticker` (`src/lib/ticker-settings.ts`), the key that sends a reply under `canopy-send-key`
(`src/lib/send-key.ts`), and each list's order under `canopy-list-order` (`src/lib/list-order.ts`), all synced across
tabs. The ticker keeps the topics left out, not those shown, so a topic added later shows until it is turned off.

## Patterns

- **Lists are rows in a panel**, divided by hairlines: a fixed-width key column (a ticket key, a state), then the
  text, then readouts (cost, age) right-aligned in fixed widths. Ages are `Age`: the CLI's largest whole unit, with
  the local time on hover.
- **A list in time can be flipped**, oldest first or newest first, from its panel's header (`OrderToggle`): a
  conversation, a chore's notes, a transcript, the runs page and a ticket's or chore's recent runs, a ticket's or
  tick's decisions, the ticks, and the tickets. The toggle is a ghost button before the count, an up-down arrow and
  the order it is in, in words (`newest first`); a click shows the other. Each list starts in the order the server
  sends it and keeps the operator's choice for that list alone, wherever it appears: a conversation flipped on a
  ticket's page is flipped in the inbox too. It shows only when the list has two items or more.
- **A list that grows without bound scrolls inside its panel** (`PanelScroll`) when other panels sit under it in the
  same column: a ticket's recent runs and decisions, a chore's open findings and recent runs. Past `28rem` the rows
  scroll under the panel's header, with a thin scrollbar, so the panels below stay in reach. The region takes focus,
  so the keyboard scrolls it too. A list that is its page's main content (the runs page, a tick's decisions) does
  not: the page scrolls instead.
- **The runs page is a row per ticket** (`TicketRunsTable`, `byTicket` in `src/lib/run-state.ts`): the ticket's latest
  run, which says where it stands, and under it `N earlier runs`, a toggle in the accent that opens the runs before it,
  newest first, each one line in the row's own columns: its state, the first line of what it said in muted text where
  the title is, its id and chips, cost, and when; the rest is on its run's page. The head line leads with the ticket:
  the state, the key, and the title, which takes the free width, then the run's id and chips in a fixed-width column, so
  every row's title and run id line up whatever chips a run has. What goes under it (the summary, the PRs, the toggle)
  starts under the title. A ticket that asked, got its answer, and asked again is one blocked row, not two. The state
  filter goes by each ticket's latest run, and so do the rail's working runs and the Running counter's `N blocked`: a
  blocked run a later one followed waits on nothing. A ticket's page lists its runs flat (`RunsTable`), since every row
  there is the same ticket's.
- **Chips** (`Chip`) label a row with a fixed word: a kind, `private`, a reason. Never with journal text. A word
  the journal stores (a reason, an action, a kind, a phase) goes in as `word` and reads as words: underscores become
  spaces and an action's prefix takes a space after its colon (`worker failed`, `attention: needs reviewer`), while
  the CLI's spelling stays on hover, so it can still be found in `attention.md` or typed into the CLI
  (`src/lib/words.ts`).
- **A ticket's title** (`TicketTitle`) follows its key, in medium weight, so it reads as the row's name and apart
  from what a run said under it; one line, cut to fit, the whole on hover. A ticket's page heading sets the key in
  muted mono before it. Nowhere too narrow to show more than a few letters of it: the Working panel leaves it out.
- **Counters** (`Counter`, `src/components/counter.tsx`) head the attention page (running, waiting on you, and
  attention; the spend is in the rail) and the worktrees page (working, held, needs a look, free, across every pool).
  Each is a label, the value, and one line under it, with a 2px top rule in the state color it counts:
  `status-running`, `status-stopped` for held, `status-blocked`, `status-failed` while something is broken. The
  same color washes down from the rule at 12%, fading out by 70% of the counter's height; a plain counter has none.
- **A slot strip** in a pool's header: one 10px square per slot, in slot order, in the worktree state's color, an
  idle one hollow. The counts beside it say the same in words, so the strip is `aria-hidden`.
- **A slot is one line** in our state words, never treehouse's (its word is on hover, as the path is on the slot's
  number). Columns keep their width on every row, the age's included. An idle slot shows its state and number
  alone, dimmed; only a note or an unreadable branch takes a second line, wrapped to the panel. The branch and the
  processes treehouse found share what the row leaves, each cut to fit with the whole on hover: an agent can start
  a dozen, and the line still ends at the age.
- **The attention list is an inbox**: one list, most severe first, beside the selected item. Severity
  (`src/lib/attention.ts`): broken work first (a run's `crashed`, `unpushed`, `unknown_result`, `worker_failed`,
  `attempt_limit`, `chore_failed`, and the review reasons), then what waits on the operator's answer (`awaiting_reply`,
  `untrusted_review`), then every other reason, then chores' findings; within each, the item open longest first. A
  reason chip takes `status-failed` or `status-blocked` for the first two, plain otherwise. The selection is
  `?item=<id>`; with none, the most severe item about a ticket. A ticket's item shows its conversation, the reply form,
  and the ticket's actions; a chore's item (a finding or `chore_failed`) shows the chore's notes and the note form,
  and a finding a ghost `dismiss` beside its age (`useDismissFinding`); an item about neither shows its detail and
  nothing to answer. Under the list, Working lists the running runs: ticket, kind, cost so far, and for how long.
- **A conversation** is a column of messages, each a head line (id, who, kind, age) over a bubble at most `max-w-2xl`
  wide: `surface-raised` for a worker's report or a tracker comment, the `status-blocked` tint for a question, and the
  accent's tint for the operator's own words, which sit on the right. A bubble's corner nearest its side is square.
  Bodies keep their line breaks (`whitespace-pre-wrap`) and are always text, but for their URLs (below). An operator
  message no `ok` tick has read carries a `waiting for the next tick` chip in `status-running`
  (`src/lib/acknowledged.ts`), and an `awaiting_reply` item it answered an `answered` chip, with a line saying it leaves
  at the next tick; Waiting on you counts neither. While a run works the ticket, the conversation ends on it (starts on
  it, flipped newest first), on the worker's side, as a chat shows someone typing (`WorkingNow`): a pulsing `RunDot`,
  `working now` in `status-running`, its `run:N` link, its kind, its cost so far, and for how long. It comes from the
  runs on the stream, so it rises in when the run starts and leaves when it ends.
- **A URL in journal text** (`LinkedText`): an http or https URL in a message body, a summary, a rationale, or a
  detail is a link in `accent`, underlined so it reads as one inside prose, its text the URL as written; it opens in a
  new tab. A PR shown in its own place (a run's or decision's PR) stays the compact link with its icon.
- **A chore's notes** are a conversation of the operator's words alone, under the chore's runs and findings, with a
  note form (`ChoreNotes`). A note no run of the chore has started since carries `waiting for the next run` in
  `status-running` (`src/lib/chores.ts`): no tick reads a note, so the tick chip would be wrong there.
- **Decisions** are rows (`Decisions`): the subject, a ticket or chore as a link, a unit as its ticket and repository
  (on a ticket's page, the tick instead, with its age), the action as a chip, a PR as a link, and the rationale under
  them as rich text. A `refused:` action's chip is in `status-failed` and an `attention:` one's in `status-blocked`
  (`src/lib/decisions.ts`); the rest are plain. A tick in a list is its id as a link, its status in the header's tick
  colors (`src/lib/ticks.ts`), how many decisions, its cost, and when it ended.
- **A transcript** (`TranscriptPanel`) is a session's events as rows, in the order the runtime printed them, each
  with its time from the session's first event (`+12:05`; the local time on hover). The agent's text keeps its line
  breaks, its reasoning muted and italic under a `thinking` label. A tool call is a native `<details>` whose line
  says what it did and how it ended (`src/lib/transcript.ts`): a `RunDot` in `done` or `failed`, the tool's name, and
  in monospace a shell call's command (the agent's description of it on hover), else the runtime's title, else its
  input's short values as `key=value`; under that, muted, its error's first line in `status-failed`, or an output of
  one short line that is not JSON; then how long it took. A canopy command that printed a refusal is `failed`, with a
  `refused: <guard>` chip in `status-failed`. It opens to its input and its output (or error), JSON indented, in
  monospace blocks at most 24rem tall. A model call is a muted line with its tokens and cost, and its reason only when
  it is not `tool-calls`, as every call but the last is; it opens the same way to its tokens by kind, each a label
  and a readout on one line, and Open all leaves it closed. A runtime error is tinted `status-failed`. Open all and
  Close all are in the header, with the session id; above the rows, how many tool calls, failed and refused ones, and
  model calls. A
  run's id in a list (`run:N`) opens its page, which is the run's fields over its transcript, and a chore run's id
  (`#N`) its page, whose findings sit between the two; a tick's page has the overseer's under its decisions.
- **A tick's output** (`TickOutputPanel`) is the overseer's file as written, under the tick's transcript: one muted
  line naming the file until a ghost Show button in the header opens it. Open, it is one monospace block, its lines
  wrapped anywhere (JSON events have no spaces to break at), scrolling inside the panel (`PanelScroll`) and opened
  at its end, where stderr is; the file's size is in the header, and a cut says so above the block.
- **Rich text** (`RichText`, `src/lib/rich-text.ts`) lays out what an agent wrote, a run's, chore run's, or tick's
  summary and a decision's rationale: line breaks kept, `-` and `1.` lists (nested by indent), `#` headings as a
  `font-medium` line, fenced code as a `surface-raised` block that scrolls sideways, and `code` and **strong** inline.
  It reads nothing else: other markup, a labelled link's included, stays characters. Every piece is React text, and
  its text and strong pieces go through `LinkedText`, so a URL outside code is a link to itself. In a list's row it
  shows the first four lines and a `show N more lines` toggle in the accent; text one line over shows whole.
  A conversation's bubbles keep their own `whitespace-pre-wrap`.
- **A chore** is a line in `canopy status`'s words (`choreLine`: `running for 10m`, `last ok 4h ago, due in 1h`) in
  its latest run's state color, then its window (`windowText`) and its open findings. A chore run is a row like a
  run's, its id as `#2` (a chore run has no `run:ID` reference) linking to its page, with its findings as a chip on
  an `ok` run. A finding is one row (`ChoreFindingRow`) on a chore's page and a chore run's alike; an open one says
  how long it has been open, and on the chore's page has `dismiss` after its age, or once dismissed a plain
  `dismissed` chip and `list again`: still reported, only off the attention list. A row's own action is a ghost `xs`
  button in monospace in its head line, as the list-order toggle is, never a full button under the row; what it did
  goes under the row, once clicked.
- **A link out** (a PR, a ticket in the tracker, a finding) opens in a new tab with `rel="noreferrer noopener"`,
  shows its address without `https://`, and ends in the `ExternalLink` icon. A ticket's links out sit in its page's
  header, under the title and its line, so they are the first thing found (`TicketLinks`): an outline button per
  link, in the accent's monospace, its icon first (`Ticket` for the tracker, `GitPullRequest` for a PR, `GitBranch`
  for a branch), what it opens on hover.
  The tracker's comes first, when `tracker.ticket_url` is set (`useTicketUrl`), then each repository's PR, then the
  ticket's branch in each repository that has a branch link (`useBranchUrls`, design §18); an unknown ticket's
  page shows the tracker's alone. The Work panel keeps each repository's PR beside its phase. A worktree's branch
  links the same way, its name in the accent with the `ExternalLink` icon, when its repository has a branch link.
- **A reply or note form** sends on the key Settings names: Enter by default, as a chat does; Ctrl+Enter (⌘+Enter on
  a Mac), Enter making a new line; or Button only. Shift+Enter always starts a new line, and an Enter that ends an IME
  composition only commits it (`src/lib/send-key.ts`). The send button names its key in a keycap (`Kbd`) after its
  label, in the accent foreground's tint: ⏎, or ⌘⏎ on an Apple keyboard and Ctrl⏎ elsewhere; Button only shows none.
  The keycap is `aria-hidden`; the button carries the same keys as `aria-keyshortcuts`.
- **Options that are each on or off** (the ticker's topics) are a row of checkboxes (`Checkbox`,
  `src/components/ui/checkbox.tsx`), each inside its label, so a click on the word toggles it too: a box on the raised
  surface, filled with the accent and its foreground's tick when on. The row is a `fieldset` named by the line beside
  it.
- **A choice of a few fixed options** (a theme, the ticker's speed, the send key) is a segmented control
  (`ToggleGroup`, `src/components/ui/toggle-group.tsx`): the options in a well on the canvas, the picked one raised on
  `surface-raised` with `shadow-xs`. It is a radio group, so one option is always picked: the arrow keys move between
  them, Space picks one, and Tab leaves the group.
- **An action** is a button in an Actions panel or under its form, with one line under it (`Notice`): what the action
  did, in the CLI's words, or its refusal in `status-failed`, naming the guard. An action that kills something asks
  once more inline (Stop now, then End run N now), never through a browser dialog. One that cannot be undone asks
  for its subject typed out: Forget opens a form in `status-failed` that says what it drops and keeps, and its button
  stays disabled until the field holds the ticket's key exactly.
- **A review** (`/reviews/$id`) is canopy's shadow PR review, kept in the journal and posted nowhere (D114): the
  review's fields, its findings as a list linking to each one's card, and the diff, a panel per file. A diff is a
  monospace table: the old and new line numbers, the `+` or `-` in `diff-add` or `diff-del`, and the line, its row on
  that token's 12% tint; a hunk's header on `surface-raised`; long lines scroll sideways inside the panel. A finding's
  card (`FindingCard`) sits right under the line it names, or under its file's header when the diff does not show the
  line, or in a Not in the diff panel: its number, its severity as a chip (`blocking` in `status-failed`, `major` in
  `status-blocked`, as the attention list's reasons; `minor` plain), its title, its location, and its detail as rich
  text. The list of reviews is rows: the review's link, its state's dot and verdict in that state's color, its ticket
  (or `review.query`), the PR as a link out, the commit's first 7 characters, its impact, cost, and age.
- **A PR** (`/pull-requests`, `/pull-requests/pr?url=`) has a section of its own. A PR's row: the PR as a link to
  its page, its ticket and title (or `no ticket`, muted), its unit's phase as a chip, then fixed-width readouts: the run
  working it now (a pulsing dot and `run:N`), its latest review (its state's dot, `review N`, and its verdict, in the
  state's color; `not reviewed` muted), and its age. Its page: the PR's address as the title with its phase as a chip,
  a link out under it as a ticket's page has, then panels for its fields, the runs that pushed to it (`RunsTable`), its
  reviews as rows each opening the review, and its decisions. A review's page links to its PR's (`its page in
  canopy`).
- **Search** sits atop the nav on every page (`SearchBox`): a magnifier, the field, and `/` in a keycap, its shortcut
  from anywhere but a text field. While the field holds text, a ghost clear button (`X`, on the keycap's `bg-muted`
  when hovered) takes the keycap's place: it empties the field and keeps the focus there, leaving the page as it is.
  The search page has a panel per source with hits, in the server's order, its count in the header (`newest 20` when
  the source has more). A hit is a row: where it opens (its ticket or chore with the run that said it, or the tick
  that decided it), its label as a chip, the snippet with the query's words marked on the accent's tint
  (`bg-accent/20`, `src/lib/search.ts`), and its age. A snippet links nothing, since it may cut a URL short. While
  the next query's hits load, the last ones stay, dimmed to 60%.
- **Signed out**, the whole page is the sign-in card, centered on the canvas: no shell, nothing from the journal.
