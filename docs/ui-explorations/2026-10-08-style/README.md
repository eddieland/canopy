# UI style exploration, 2026-10-08

A look for alternatives to the web UI's current direction ("a scientific instrument panel", `ui/DESIGN.md`). It is a
record of ideas, not normative: `ui/DESIGN.md` still governs the UI until it is changed.

Every board draws the same Attention screen with the same content, so only the style differs. Open the `.html` files
in a browser. Each one is self-contained except for fonts from Google Fonts, which the real UI may not use (it bundles
its fonts, `ui/AGENTS.md`). The files were generated from the design canvas
(<https://claude.ai/artifact/2ukTQTppKqYBZ486S1rieh>, private to the operator). Edit them by hand from now on. Their
lines are not wrapped.

The content is invented for the mockups: ticket titles, tick numbers, "3 slots", "$2.54 spend today".

## Outcome

**E · Ops inbox** was the favorite. A, C and D were the round-one directions that worked, and E and F combine them.
B and the current look were set aside.

Feedback that applies to any next step:

- The current look felt disconnected. Our diagnosis: a lab-instrument style, a name that suggests trees and shelter,
  and a job that is mostly reading a worker's words and answering them each point somewhere different.
- Keyboard shortcuts are not a priority, and the UI does not need to match the terminal's keys. They were removed
  from E. F still shows them as drawn and should not be read as a requirement.

## Round 1: five tones

Each entry gives the file, then the type, the palette, and the idea worth keeping.

- `0-today-instrument-panel.html`, **the current UI** as a baseline. Inter and JetBrains Mono; cool slate, a cyan
  accent, a measurement grid. Keep: monospace for every number.
- `a-terminal-ledger.html`, **`canopy status` grown into a page**. IBM Plex Mono only; warm near-black and amber.
  Keep: numbered tabs, a status line with the tick countdown, `[ASK]`/`[ERR]` tags.
- `b-field-notes.html`, **editorial, follows the name**. Newsreader serif and Instrument Sans; paper and forest green.
  Keep: a headline sentence ("Four things need you"), the open question as the featured item.
- `c-control-room.html`, **a monitoring dashboard**. IBM Plex Sans and Mono; dark slate, solid state colors. Keep: big
  counters with a colored top rule, items sorted by severity.
- `d-calm-inbox.html`, **a mail app**: a teammate handing you work. Geist and Geist Mono; grey and white, indigo,
  rounded. Keep: the list beside the open thread, the thread as chat bubbles with a reply box.

## Round 2: combinations, dark and light

Both use one layout: a header in the terminal's style (tabs, live state, tick countdown), the control room's four
counters, then the attention list (by severity, with workers under it) beside the open thread and its reply box.

- `e-ops-inbox-dark.html`, `e-ops-inbox-light.html`: **E · Ops inbox**, the control room softened by the calm inbox.
  Plex Sans for text and Plex Mono for data, 6-10px radii, state chips, the thread as chat bubbles. Dark: cool slate
  with a periwinkle accent. Light: the inbox's grey and white with an indigo accent.
- `f-ledger-inbox-dark.html`, `f-ledger-inbox-light.html`: **F · Ledger inbox**, the terminal leading. All monospace,
  bracketed tags, the thread as a timestamped transcript with a `>` reply prompt. Dark: warm near-black and amber.
  Light: paper, ink and a deeper amber.

### E's palette

| Role | Dark | Light |
|---|---|---|
| background | `#0b0e13` | `#eef0f3` |
| surface | `#11151c` | `#ffffff` |
| surface-raised | `#1a202a` | `#f3f4f7` |
| border | `#232b38` | `#dde0e6` |
| foreground | `#e8edf5` | `#1c1d22` |
| body text | `#c9d1dd` | `#2a2c33` |
| muted-foreground | `#7d8899` | `#5d6070` |
| accent | `#8ea2ff` | `#3550c8` |
| status-running | `#3ddc97` | `#1f8a5b` |
| status-blocked (waiting) | `#ffb547` | `#a86400` |
| status-failed | `#ff6b6b` | `#c0392b` |
| review | `#4fd1e0` | `#0f7c8c` |
| spend | `#c4a7ff` | `#6d4fc4` |

These were chosen by eye and not checked for contrast. Chips and the question bubble tint their state color at about
13% alpha.

## If E is adopted

These need decisions, not just new tokens:

- **New tokens.** Body text separate from foreground, a review color, and a spend color have no token in
  `ui/src/styles/tokens.css` yet. Convert the values to oklch to match that file.
- **Counters move into the page.** The header's live readouts become four counters at the top of the page, and spend
  today joins them (it needs an API field).
- **Attention order.** The page groups items by reason today. E sorts one list by severity.
- **Layout.** Today each page is a stack of panels. E makes Attention a list beside a detail view, so a ticket's
  thread and reply open next to the list instead of on the ticket page.
- **Typeface.** IBM Plex replaces Inter and JetBrains Mono. It is available from `@fontsource`.
- **Docs.** The direction in `ui/DESIGN.md` is rewritten in the same PR.
