# ui/AGENTS.md

Rules for any agent working in `ui/`, the web UI (D076). The repository's `AGENTS.md` still applies; this adds what is
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
  `src/components/ui/button.tsx` was: style classes inlined, `dark:` overrides replaced with tokens.
- TanStack Router (file-based, `src/routes/`) and TanStack Query.
- oxlint (with the React Compiler's rules) and oxfmt, Vitest, Playwright.

## Commands

From `ui/` (or `make ui-check`, `make ui-e2e`, `make ui-fmt` from the root):

| Command | Does |
|---|---|
| `npm run dev` | Vite on 127.0.0.1:5173, proxying `/api` to `npm run dev:api` (FastAPI with mock data on :8765) |
| `npm run check` | format check, lint, typecheck, generated types current, unit tests, build. Must pass. |
| `npm run fmt` | format with oxfmt |
| `npm run gen:api` | regenerate `src/api/schema.gen.ts` from `canopy.serve`'s OpenAPI schema |
| `npm run test:e2e` | build, then Playwright against the build served by FastAPI |

With no network for Playwright's browser, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to a local Chromium.

## Rules

- **Tokens only.** No raw colors and no `dark:` in components; a theme difference is a token change. The lint enforces
  it. See `DESIGN.md`.
- **No hand-written memoization.** The compiler memoizes. `useMemo`, `useCallback`, and `memo` are banned by the lint.
  Follow the compiler's rules (no setState directly in an effect body, no reading refs during render, ...).
- **Types come from the server.** API types are generated from `src/canopy/serve/schema.py`. To change a shape,
  change the pydantic model, run `npm run gen:api`, and commit both. Import types from `src/api/types.ts`.
- **One place per query.** Keys and fetchers live in `src/api/queries.ts`; components call `useQuery(xQuery)`.
- **Live data comes from the stream, not polling.** No `refetchInterval`. Server pushes arrive through
  `useEventStream` and are written with `setQueryData` (`src/api/live.ts`, `src/hooks/use-live-updates.ts`). A new
  event type is a pydantic model in the `StreamEvent` union, a case in `applyStreamEvent`, and a check in
  `parseStreamEvent`.
- **Never blank content.** A skeleton only when `data` is `undefined`. Reserve space for anything async.
- **Typed search params.** Validate in the route's `validateSearch` and return every key, `undefined` when invalid:
  the router merges the result over the raw search, so an omitted key keeps the raw string (see `routes/sessions.tsx`).
- **URLs are relative to the base path.** The app may be served under a prefix. Use `apiUrl()` and `basePath` from
  `src/lib/base.ts` and router `Link`s; never write `/api/...` or `/assets/...` as an absolute path.
- **No requests to another origin** at run time: no CDN fonts, icon fonts, analytics, or remote images. Bundle them.
- **Untrusted text stays text.** Journal content (tracker comments, agent output) is rendered as React children, never
  through `dangerouslySetInnerHTML`.
- **Formatting:** oxfmt, 120 columns, 4-space indent (the repository's `.editorconfig`). A formatter does not split a
  long string: split class lists across `cn()` or `cva()` arguments. The lint fails on a line over 120.
- **Mocks are flagged.** `/api/sessions`, `/api/leases`, and `/api/events` serve fixtures (`canopy/serve/mock.py`,
  `src/api/mocks.ts`) until the journal backs them; the header shows `mock`. Keep the fixtures matching the schema.

## Python side

Keep it to serving and wiring, in `src/canopy/serve/` (`docs/DESIGN.md` §5, §22). The SPA fallback, caching, CSP,
Host and Origin checks, and base path are there and tested in `tests/canopy/test_serve.py`; a new route under `/api`
needs no change to them. The server is not yet run by `canopy loop` (ROADMAP M20).

## Tests

- Unit tests (Vitest, happy-dom) sit next to the code as `*.test.ts(x)`. Test logic, not markup.
- Playwright (`e2e/`) runs against the production build served by FastAPI, never the Vite dev server. Every route
  gets a screenshot per theme in `e2e/screenshots.spec.ts`. A visual change updates the baselines deliberately
  (`npx playwright test --update-snapshots`) and the PR says why; look at each new image before committing it.

## Done for a UI pull request

- `make check` passes (it runs `npm run check`), and `make ui-e2e` passes.
- New behavior has a unit test or a Playwright test; a new route has its screenshots.
- `DESIGN.md` here is updated for any new token, pattern, or rule.
