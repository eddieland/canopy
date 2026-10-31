# ui/AGENTS.md

Rules for any agent working in `ui/`, the web UI (D079). The repository's `AGENTS.md` still applies; this adds what is
specific here. Read `DESIGN.md` in this directory before changing anything visible.

## Stack

Pinned exactly in `package.json`. Check the current docs for these versions before using an API; do not code from
memory, and do not upgrade in passing.

- Vite 8 single-page app. No Next.js, no server rendering.
- React 19.3 with the React Compiler (`@vitejs/plugin-react` `compiler: true`). `<ViewTransition>` and
  `useEffectEvent` are stable in 19.3: never install `react@canary`.
- TypeScript strict, with `noUncheckedIndexedAccess`.
- Tailwind v4, configured in CSS (`src/index.css`, `src/styles/tokens.css`). There is no `tailwind.config.js`.
- shadcn/ui on Radix, Vega style (`components.json`). Add components with `npx shadcn add <name>` and read
  `npx shadcn docs <name>`. If the registry is unreachable, port the source from shadcn's repository by hand as
  `src/components/ui/button.tsx` was: style classes inlined, `dark:` overrides replaced with tokens. Those wrappers are
  the only code that imports Radix, from the one `radix-ui` package; the lint refuses it, and any `@radix-ui/*`,
  elsewhere. A control Radix has a primitive for uses its wrapper, never hand-written ARIA state (`DESIGN.md`).
- TanStack Router (file-based, `src/routes/`) and TanStack Query.
- Tiptap on ProseMirror for the plan editor alone (D120): only `src/lib/plan-*.ts` and
  `src/components/plan-editor.tsx` import it, and only the pages that show a plan load it: a ticket's plan page, the
  sample editor, and a task's page, whose report it lays out read only (`PlanDocument`); never the ticket's page,
  whose plan card does not import it.
- Shiki for a review's diff and the guide's code blocks alone (D121): only `src/lib/highlight.ts` and
  `src/lib/languages.ts`, its grammars, import it, and only on demand, each grammar its own chunk.
- mermaid for a plan's diagrams and the guide's alone (D131): only `src/lib/diagram.ts` imports it, and only on
  demand, from `src/lib/plan-diagram.ts` and `src/hooks/use-diagram.ts`, which show what it draws only as an image
  (mermaid lays the SVG out off screen while it draws, sanitized).
- jsdiff (`diff`) for a plan's word diff alone: only `src/lib/plan-diff.ts` imports it.
- cmdk for the repository picker's, the model picker's, and the jump palette's searchable lists, which Radix has no
  primitive for: only `src/components/ui/command.tsx` imports it, and the lint refuses it elsewhere.
- oxlint (with the React Compiler's rules, eslint-plugin-jsdoc's, eslint-plugin-playwright's on `e2e/`, and
  type-aware rules through oxlint-tsgolint) and oxfmt, Vitest, Playwright.

Add a library as the repository's `AGENTS.md` says, when it clearly beats the code we would write instead, and pin it
exactly like the rest. One that only a few files need is held to them, as Tiptap (D120) and Shiki (D121) are.

## Commands

From `ui/` (or `make ui-check`, `make ui-e2e`, `make ui-fmt` from the root):

| Command | Does |
|---|---|
| `npm run dev` | Vite on 127.0.0.1:5173, proxying `/api` to `npm run dev:api` (FastAPI over a mock journal on :8765) |
| `npm run check` | format check, lint, typecheck, generated types current, unit tests, build: what CI runs |
| `npm run fmt:check`, `lint`, `typecheck`, `check:api` | its pieces, one at a time |
| `npm test -- <files>` | the Vitest files named |
| `npm run fmt` | remove unused imports (oxlint), then format and sort imports with oxfmt |
| `npm run gen:api` | regenerate `src/api/schema.gen.ts` from `canopy.serve`'s OpenAPI schema |
| `npm run test:e2e -- <specs>` | build, then Playwright against it, served by FastAPI; every spec when none is named |

With no network for Playwright's browser, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to a local Chromium. It tests behavior,
not looks: a build other than the one the pinned Playwright installs draws differently, so its screenshots fail by the
dozen. When every screenshot differs, check the browser before the change.

## Rules

- **The lint is strict.** oxlint runs every rule in its correctness, suspicious, pedantic, and perf categories, and
  the style and restriction rules `.oxlintrc.json` names one by one; a rule turned off there says why. It runs with
  `--type-aware`, so the rules that need types run too: a floating promise, a deprecated API, a condition that is
  always true, a switch that misses a case, a number tested for truth. Fix what it finds. A line that must break a
  rule carries `oxlint-disable-next-line` with the rule's name and a comment saying why.
- **Imports go down.** Each directory of `src/` is a layer, and imports only from those below it: `api/` (the
  client, queries, mutations, and the server's types), then `lib/` (logic over them, and the hooks that keep a
  setting), `theme/`, `hooks/`, `components/ui/` (the shadcn wrappers, which know nothing of canopy's data), then
  `components/`, `components/shell/` (the frame every page sits in), and `routes/`. A component a page and the shell
  both use lives in `components/`. The route tree's types may be named anywhere, and a test may import what sits above
  the code it tests. `npm run lint` refuses the rest, and a held library outside its files (Stack), with
  `scripts/check-imports.mjs`, whose `LAYERS` says what each layer may import.
- **Tokens only.** No raw colors and no `dark:` in components; a theme difference is a token change. The lint enforces
  it. See `DESIGN.md`.
- **Every export has a JSDoc comment**, and so does each field of an exported interface: what it is or does, in
  prose. No types in it (`@param {string}`): TypeScript has them. The lint enforces both (`jsdoc-js` in
  `.oxlintrc.json`); a public member of an exported class needs one too, which the lint does not check.
- **No hand-written memoization.** The compiler memoizes. `useMemo`, `useCallback`, and `memo` are banned by the lint.
  Follow the compiler's rules (no setState directly in an effect body, no reading refs during render, ...).
- **Types come from the server.** API types are generated from the pydantic models in `src/canopy/serve/schema/`:
  the shared ones in its `__init__.py`, and each feature's in a module of its own. To change a shape, change the
  pydantic model, run `npm run gen:api`, and commit both. Import types from `src/api/types.ts`.
- **One place per query.** Keys and fetchers live in `src/api/queries.ts`; components call `useQuery(xQuery)`.
- **Live data comes from the stream, not polling.** No `refetchInterval`, but for the worktrees and the host's
  resources. Server pushes arrive through
  `useEventStream` (`src/api/live.ts`, `src/hooks/use-live-updates.ts`): a list arrives whole and is written with
  `setQueryData`; `ticket.changed` marks that ticket's query stale, which refetches only if a page shows it, as
  `task.changed` does a task's and its reports, and
  `chores.updated` marks every chore's (a new note changes the list it carries); `tick.updated` marks the ticks, a
  tick's page, and the ticket shown. A new
  event type is a pydantic model in the `StreamEvent` union, a case in `applyStreamEvent`, and a check in
  `parseStreamEvent`. The worktrees are one query not on the stream, since each read runs `treehouse status` and
  briefly takes every pool's lock: `runs.updated` marks them stale when the running runs' worktrees change, the page's
  Read again button refetches them, and they refetch every 10 seconds while a page shows them in a visible tab. The
  host's resources (`hostQuery`), which the header's readout shows on every page, are the other: none of them is in
  the journal, and a read is a few small files, so they refetch every 10 seconds while the tab is visible, as the
  system page's graphs' readings (`hostSamplesQuery`), which the server keeps in memory, and its processes
  (`hostProcessesQuery`) do while it is open.
- **Writes are mutations in `src/api/mutations.ts`.** Each calls the same server function as the CLI's verb, or, for
  what no command would do, a core function of its own with its guards, which TRUST_MODEL T8 names (D127); the
  client adds the session's token (`writeToken` in `src/api/client.ts`). A refusal is an `ApiError` with its `guard`;
  show it with `Notice`, which names the guard as the CLI does. Say what an action did in the CLI's words
  (`src/lib/outcomes.ts`).
- **Signed out is a state, not a route.** The shell shows the sign-in page whenever the session query says signed
  out, and any 401 sets that (`src/lib/query-client.ts`). Never keep the listener secret in the page: it is sent once,
  to `POST /api/session`.
- **Never blank content.** A skeleton only when `data` is `undefined`, and only while the read is pending: a page's
  main panel uses `PanelLoading`, which says why a failed read failed and reads again. Reserve space for anything
  async.
- **Typed search params.** Validate in the route's `validateSearch` and return every key, `undefined` when invalid:
  the router merges the result over the raw search, so an omitted key keeps the raw string (see
  `routes/runs.index.tsx`).
- **URLs are relative to the base path.** The app may be served under a prefix. Use `apiUrl()` and `basePath` from
  `src/lib/base.ts` and router `Link`s; never write `/api/...` or `/assets/...` as an absolute path.
- **No requests to another origin** at run time: no CDN fonts, icon fonts, analytics, or remote images. Bundle them.
- **Untrusted text stays text.** Journal content (tracker comments, agent output) is rendered as React children, never
  through `dangerouslySetInnerHTML`, which the lint refuses (`react/no-danger`). Free text goes through `LinkedText`
  (`src/components/linked-text.tsx`), which links its http and https URLs and nothing else (D113), except inside an
  element that is already a link. A plan in the plan editor is the one exception, not rendered by React: ProseMirror
  draws it from its schema (`src/lib/plan-schema.ts`), which keeps HTML and images as their characters and draws no
  link, so it stays text all the same. A node added to that schema keeps it so. A Mermaid fence is drawn beside its
  code as an image (D131), which runs no script and fetches nothing.
- **Formatting:** oxfmt, 120 columns, 4-space indent (the repository's `.editorconfig`). A formatter does not split a
  long string: split class lists across `cn()` or `cva()` arguments. The lint fails on a line over 120.
- **Imports are sorted, not arranged.** oxfmt sorts them by path in groups (`sortImports` in `.oxfmtrc.json`):
  node's, packages, the app's own (`@/`), relative, then stylesheets. `npm run fmt` first removes unused imports
  (`.oxlintrc.unused-imports.json`), so run it rather than tidying them by hand.
- **Mocks are flagged.** `python -m canopy.serve --mock` serves the real API over a journal seeded from
  `canopy/serve/mock/`, a workspace of three repositories; the header shows `mock`. Its times are fixed around
  2026-10-08 12:00 UTC: a screenshot test freezes the browser's clock (`NOW` in `e2e/helpers.ts`). `src/api/mocks.ts`
  holds a few typed rows for unit tests.
- **The guide says what the pages do.** The operator's documentation is Markdown in `src/guide/` (`DESIGN.md`, "The
  guide"). A change to what a page shows or does updates the guide's page about it in the same PR, as a change to a
  behavior updates the design. Its links are checked by `src/lib/guide.test.ts`.
- **The guide has a voice.** World-class developer docs, with the undertone of a funny, sage staff engineer. Talk to
  the operator as `you`, in plain, direct sentences: lead with what a thing does and how to use it. The humor is dry
  and earned, an aside from someone who has seen a few incidents, never a pun for its own sake: it rides on a fact,
  never stands in for one, and stays rare enough to land (a few to a page, not one a line). Use dashes sparingly.
  `src/guide/overview.md` sets the bar; this voice is the guide's alone, not the CLI's, the design's, or a page's.
- **API docs.** The server serves Swagger UI at `/api/docs`, over the schema at `/api/openapi.json`, from the copy
  `vite.config.ts` puts in the build's `api-docs/`: through the dev server too, once `npm run build` has run.

## Python side

Keep it to serving and wiring, in `src/canopy/serve/` (DESIGN §5, §22). The SPA fallback, caching, CSP,
Host and Origin checks, sign-in, and base path are there and tested in `tests/canopy/serve/test_serve.py`; the API
over a real journal and `canopy loop` serving it in `tests/canopy/serve/test_web.py`. A new route under `/api` goes in
its resource's module in `api/`, or in a new one listed on the signed-in router in `api/__init__.py`, and needs no
change to the rest; a write goes through `canopy.core.conversation`, never SQL of its own.

## Tests

- Unit tests (Vitest, happy-dom) sit next to the code as `*.test.ts(x)`. Test behavior, and what a component renders
  when that is the behavior: what shows in each state, its accessible names and roles, and words the CLI shares (a
  refusal's guard). Find elements by role, name, and text, as a person or a screen reader does, never by class, tag, or
  DOM shape; how it looks is the screenshots' job.
- Playwright (`e2e/`) runs against the production build served by FastAPI, never the Vite dev server. The root server
  needs the listener secret (`e2e/secret.ts`; `signIn` in `e2e/helpers.ts`) and never changes its journal; tests that
  write run against the prefixed one. Every route gets a screenshot in dark in `e2e/screenshots.spec.ts`, of its main
  pane alone, so a change to the header or the rail rewrites a few images rather than every one. The pages `README.md`
  shows are taken whole (`WHOLE_ROUTES` in `e2e/helpers.ts`), and a few are taken in light as well (`LIGHT_ROUTES`):
  both themes draw from the same tokens, so more would double the images git keeps for every visual change without
  catching more. Add a page to either only for what the others cannot show. A visual change updates the baselines
  deliberately and the PR says why; look at each new image before it merges. The Screenshots workflow never deletes an
  image: a PR that stops taking one deletes its baseline. Every screenshot applies `e2e/screenshot.css`, which replaces
  what changes with the build rather than the page (the rail's version, which names the commit, shows a placeholder as
  long as a dev build's, and the mock's private config path, in a temporary directory, is hidden). The guide's
  screenshot shows how a page is drawn, not what the guide says, which most UI pull requests edit: `placeholderGuide`
  serves a guide of placeholder Latin in place of the real one, its pages and their list included, with
  `e2e/guide-specimen.md` the page taken, so a guide edit rewrites no image. `README.md` shows `attention-dark`,
  `tickets-ABC-102-dark`, `workspace-runs-39-dark`, `pull-requests-reviews-4-dark`, and `workspace-ticks-2-dark`:
  rename them there too. The baselines are CI's Chromium and fonts, so regenerate them there: push the branch, then run
  the Screenshots workflow on it (`gh workflow run screenshots.yml --ref BRANCH`, or the Actions tab, or an agent's
  GitHub tools). It runs only the spec files that call `toHaveScreenshot`, `screenshotMain`, or `screenshotWhole`, so a
  test that takes one through another helper is missed until its file calls one of those. It pushes a commit with the
  images that changed, recompressed losslessly with oxipng, and starts CI on it, which runs the whole suite; pull before
  going on. It rewrites only the images that fail the comparison, so a change subtle enough to pass within the threshold
  (a token's small shift) leaves the old images in place: run it with `update` set to `all` (`-f update=all`) to rewrite
  every one. The workflow stays CI's way. `make screenshots` renders the same images locally in Docker (it needs
  Docker), from Playwright's Ubuntu image at the pinned version, with the same spec files and oxipng, and writes only
  the images that changed into the checkout; `UPDATE=all` rewrites every one and `UPDATE=check` only compares. `npx
  playwright test --update-snapshots=changed` outside Docker runs on a machine whose rendering may not match.
- On CI, Playwright runs a failed test once more, and one that passes then still fails the run, named flaky in the
  report: fix it, as a broken one is. The lint holds `e2e/` to eslint-plugin-playwright's recommended rules, which
  refuse most of what makes a browser test flaky.
- Playwright hides scrollbars in headless Chromium, so those screenshots never show one. `e2e/scrollbars.spec.ts`
  keeps them, for what a scrollbar is part of: a long list scrolling in its panel.

## Done for a UI pull request

- The checks pass, run as the repository's `AGENTS.md` says (Toolchain): every formatter and linter (`make fmt`,
  `make lint`, `npm run lint`, `npm run typecheck`), `check:api` when a pydantic model behind the API changed,
  `npm test` for the unit tests of what changed, and `npm run test:e2e` for the Playwright specs that cover it. CI runs
  the rest.
- New behavior has a unit test or a Playwright test; a new route has its screenshots.
- `DESIGN.md` here is updated for any new token, pattern, or rule, and the guide for anything a page of it describes.
  Fun is the exception: what the ticker, Sprig, the rave, and the like do is written in their code, and `DESIGN.md`
  keeps only the rules all fun shares (its Fun section), changed only when one of those changes.
