import { defineConfig, devices } from '@playwright/test'

import { E2E_SECRET } from './e2e/secret.ts'

// End-to-end tests run against the production build served by FastAPI (canopy.serve), never the Vite dev server:
// that is what operators get, base href, CSP, and SPA fallback included. `npm run test:e2e` builds first.
//
// Two servers, both over a journal seeded from fixtures (canopy/serve/mock/):
//   root      at /, behind the listener secret E2E_SECRET, with no changes to the journal, so screenshots are stable
//   prefixed  at /canopy, signing nobody in, changing the journal every 250 ms, for the base path, live updates, and
//             writes (which would change root's screenshots)
const ROOT_PORT = 8766
const PREFIXED_PORT = 8767

const serve = (args: string): string => `uv run --quiet python -m canopy.serve --mock --ui-dir ui/dist ${args}`
// The secret file must be the operator's alone (canopy/serve/secret.py), which git cannot check out: write one.
const withSecret = (args: string): string =>
    `sh -c 'umask 077 && d=$(mktemp -d) && printf %s ${E2E_SECRET} > "$d/secret" && ` +
    `exec ${serve(`--secret-file "$d/secret" ${args}`)}'`

/** Playwright against the production build, served by FastAPI over the mock journal: never the Vite dev server. */
export default defineConfig({
    testDir: './e2e',
    fullyParallel: true,
    forbidOnly: Boolean(process.env.CI),
    // On CI a failed test runs once more, and passing then still fails the run: the report names it flaky rather than
    // failed, so a flake is told from a break at a glance, and is fixed, never let through.
    retries: process.env.CI ? 1 : 0,
    failOnFlakyTests: Boolean(process.env.CI),
    reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
    expect: {
        // Fonts are self-hosted and animations are frozen; what is left is antialiasing between Chromium builds.
        // The rail's version names the commit it was built from, so every commit would change every image: hidden.
        toHaveScreenshot: {
            maxDiffPixels: 0,
            animations: 'disabled',
            caret: 'hide',
            stylePath: './e2e/screenshot.css',
        },
    },
    use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1280, height: 800 },
        trace: 'retain-on-failure',
        launchOptions: {
            // A preinstalled Chromium when Playwright's own build is not downloaded (PLAYWRIGHT_CHROMIUM_EXECUTABLE).
            executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined,
        },
    },
    projects: [
        {
            name: 'root',
            testIgnore: /prefixed\.spec\.ts/u,
            use: { baseURL: `http://127.0.0.1:${ROOT_PORT}` },
        },
        {
            name: 'prefixed',
            testMatch: /prefixed\.spec\.ts/u,
            use: { baseURL: `http://127.0.0.1:${PREFIXED_PORT}/canopy/` },
        },
    ],
    webServer: [
        {
            command: withSecret(`--port ${ROOT_PORT} --mock-event-seconds 0`),
            cwd: '..',
            url: `http://127.0.0.1:${ROOT_PORT}/api/session`,
            reuseExistingServer: !process.env.CI,
        },
        {
            command: serve(`--port ${PREFIXED_PORT} --base-path /canopy --mock-event-seconds 0.25`),
            cwd: '..',
            url: `http://127.0.0.1:${PREFIXED_PORT}/canopy/api/session`,
            reuseExistingServer: !process.env.CI,
        },
    ],
})
