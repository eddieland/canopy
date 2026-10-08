import { defineConfig, devices } from '@playwright/test'

// End-to-end tests run against the production build served by FastAPI (canopy.serve), never the Vite dev server:
// that is what operators get, base href, CSP, and SPA fallback included. `npm run test:e2e` builds first.
//
// Two servers, both with mock data:
//   root      at /, with no stream events, so screenshots are stable
//   prefixed  at /canopy, with an event every 250 ms, for the base path and live updates
const ROOT_PORT = 8766
const PREFIXED_PORT = 8767

const serve = (args: string): string => `uv run --quiet python -m canopy.serve --mock --ui-dir ui/dist ${args}`

export default defineConfig({
    testDir: './e2e',
    fullyParallel: true,
    forbidOnly: Boolean(process.env.CI),
    retries: 0,
    reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
    expect: {
        // Fonts are self-hosted and animations are frozen; what is left is antialiasing between Chromium builds.
        toHaveScreenshot: { maxDiffPixelRatio: 0.01, animations: 'disabled', caret: 'hide' },
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
            testIgnore: /prefixed\.spec\.ts/,
            use: { baseURL: `http://127.0.0.1:${ROOT_PORT}` },
        },
        {
            name: 'prefixed',
            testMatch: /prefixed\.spec\.ts/,
            use: { baseURL: `http://127.0.0.1:${PREFIXED_PORT}/canopy/` },
        },
    ],
    webServer: [
        {
            command: serve(`--port ${ROOT_PORT} --mock-event-seconds 0`),
            cwd: '..',
            url: `http://127.0.0.1:${ROOT_PORT}/api/meta`,
            reuseExistingServer: !process.env.CI,
        },
        {
            command: serve(`--port ${PREFIXED_PORT} --base-path /canopy --mock-event-seconds 0.25`),
            cwd: '..',
            url: `http://127.0.0.1:${PREFIXED_PORT}/canopy/api/meta`,
            reuseExistingServer: !process.env.CI,
        },
    ],
})
