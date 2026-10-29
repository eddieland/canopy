import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import {
    diffFile,
    placeholderGuide,
    LIGHT_ROUTES,
    NOW,
    OTHER_PALETTES,
    ROUTES,
    screenshotMain,
    screenshotWhole,
    serveReview,
    settled,
    signIn,
    storePalette,
    storeTheme,
    THEMES,
    WHOLE_ROUTES,
} from './helpers.ts'
import type { DiffFinding } from './helpers.ts'

// The operator's window (PRODUCT.md): half their 3440×1440 ultrawide, about as wide as the MacBook they also use.
test.use({ viewport: { width: 1720, height: 1320 } })

for (const theme of THEMES) {
    for (const route of ROUTES.filter((r) => theme === 'dark' || LIGHT_ROUTES.includes(r))) {
        test(`${route} in ${theme}`, async ({ page }) => {
            await page.clock.setFixedTime(NOW)
            await storeTheme(page, theme)
            await signIn(page)
            if (route === 'guide/overview') {
                await placeholderGuide(page, 'overview')
            }
            await page.goto(route)
            await settled(page)
            if (route === 'guide/overview') {
                await expect(page.getByRole('heading', { level: 1 })).toHaveText('Lorem ipsum')
                // Its code block is taken colored, once the grammar has loaded.
                await expect(page.locator('pre[data-highlighted]')).toBeVisible()
            }
            await expect(page.locator('html')).toHaveClass(theme === 'dark' ? /\bdark\b/u : /^(?!.*\bdark\b)/u)
            const screenshot = WHOLE_ROUTES.includes(route) ? screenshotWhole : screenshotMain
            await screenshot(page, `${route.replaceAll(/[/?=]/gu, '-')}-${theme}.png`)
        })
    }

    // What a page shows only when opened: JSON colored in a tool call's input and output, and in a tick's output.
    test(`an opened tool call in ${theme}`, async ({ page }) => {
        await page.clock.setFixedTime(NOW)
        await storeTheme(page, theme)
        await signIn(page)
        await page.goto('runs/39')
        await settled(page)
        const call = page.getByTestId('transcript-tool').filter({ hasText: 'jira_get_issue' }).first()
        await call.locator('summary').click()
        await expect(call).toHaveScreenshot(`runs-39-tool-call-${theme}.png`)
    })

    // A transcript's context chart, its fills tokens of their own in each theme.
    test(`a transcript's context chart in ${theme}`, async ({ page }) => {
        await page.clock.setFixedTime(NOW)
        await storeTheme(page, theme)
        await signIn(page)
        await page.goto('runs/39')
        await settled(page)
        const context = page.getByTestId('transcript-context')
        await context.getByRole('button', { name: 'Show chart' }).click()
        await expect(context.getByRole('radiogroup', { name: 'Model calls' })).toBeVisible()
        await expect(context).toHaveScreenshot(`runs-39-context-${theme}.png`)
    })

    test(`a tick's output pretty in ${theme}`, async ({ page }) => {
        await page.clock.setFixedTime(NOW)
        await storeTheme(page, theme)
        await signIn(page)
        await page.goto('runs/ticks/2')
        await settled(page)
        const output = page.getByTestId('tick-output')
        await output.getByRole('button', { name: 'Show output' }).click()
        await output.getByRole('button', { name: 'Pretty' }).click()
        await expect(output.getByRole('button', { name: 'Pretty' })).toHaveAttribute('aria-pressed', 'true')
        await expect(output).toHaveScreenshot(`ticks-2-output-pretty-${theme}.png`)
    })

    // The jump palette over a ticket's page, two others viewed a while before: the box alone, so the page under it
    // changes none of these.
    test(`the jump palette in ${theme}`, async ({ page }) => {
        await page.clock.setFixedTime(NOW)
        await storeTheme(page, theme)
        const viewed = [
            { key: 'ABC-099', title: null, viewedAt: minutesBefore(3) },
            { key: 'ABC-105', title: null, viewedAt: minutesBefore(48) },
        ]
        await page.addInitScript((list) => {
            localStorage.setItem('canopy-recent-tickets', list)
        }, JSON.stringify(viewed))
        await signIn(page)
        await page.goto('tickets/ABC-102')
        await settled(page)
        await page.keyboard.press('Control+k')
        const palette = page.getByTestId('jump-palette')
        await expect(palette.getByRole('option')).toHaveCount(2)
        await expect(palette).toHaveScreenshot(`jump-palette-${theme}.png`)
    })

    test(`sign-in in ${theme}`, async ({ page }) => {
        await storeTheme(page, theme)
        await page.goto('attention')
        await expect(page.getByRole('heading', { level: 1 })).toHaveText('Sign in')
        await page.evaluate(async () => {
            await document.fonts.ready
        })
        await expect(page).toHaveScreenshot(`sign-in-${theme}.png`, { fullPage: true })
    })
}

// Every palette but a theme's default sets only the neutrals, so one page in each shows all it changes: its main pane
// alone, so a change to the header or the rail rewrites none of these.
for (const theme of THEMES) {
    for (const palette of OTHER_PALETTES[theme]) {
        test(`attention in ${palette} ${theme}`, async ({ page }) => {
            await page.clock.setFixedTime(NOW)
            await storeTheme(page, theme)
            await storePalette(page, theme, palette)
            await signIn(page)
            await page.goto('attention')
            await settled(page)
            await expect(page.locator('html')).toHaveAttribute(`data-${theme}-palette`, palette)
            await screenshotMain(page, `attention-${palette}-${theme}.png`)
        })
    }
}

// A PR's feedback plan in each state it has, each on a PR of its own (canopy/serve/mock/feedback_plans.py): the panel
// alone, so a change to it rewrites these small images rather than a PR's whole page.
const FEEDBACK_PLANS = [
    { name: 'stale', status: 'stale', pr: 'https://github.com/acme/web/pull/88' },
    { name: 'waiting', status: 'waiting', pr: 'https://github.com/acme/mobile/pull/67' },
    { name: 'approved', status: 'approved', pr: 'https://github.com/acme/mobile/pull/63' },
    { name: 'approved-by-planner', status: 'approved', pr: 'https://github.com/acme/mobile/pull/62' },
    { name: 'spent', status: 'spent', pr: 'https://github.com/acme/mobile/pull/61' },
    { name: 'no-items', status: 'waiting', pr: 'https://github.com/acme/mobile/pull/65' },
    { name: 'missing', status: 'waiting', pr: 'https://github.com/acme/mobile/pull/64' },
    { name: 'many-items', status: 'waiting', pr: 'https://github.com/acme/mobile/pull/66' },
] as const

for (const theme of THEMES) {
    for (const { name, status, pr } of FEEDBACK_PLANS) {
        test(`the ${name} feedback plan in ${theme}`, async ({ page }) => {
            await page.clock.setFixedTime(NOW)
            await storeTheme(page, theme)
            await signIn(page)
            await page.goto(`pull-requests/pr?url=${encodeURIComponent(pr)}`)
            await settled(page)
            const plan = page.getByTestId('feedback-plan')
            await expect(plan).toHaveAttribute('data-status', status)
            await expect(plan).toHaveScreenshot(`feedback-plan-${name}-${theme}.png`)
        })
    }
}

// A tick's output as plain text: no color of its own, so dark alone.
test("a tick's output shown in dark", async ({ page }) => {
    await page.clock.setFixedTime(NOW)
    await storeTheme(page, 'dark')
    await signIn(page)
    await page.goto('runs/ticks/2')
    await settled(page)
    const output = page.getByTestId('tick-output')
    await output.getByRole('button', { name: 'Show output' }).click()
    await expect(output.getByTestId('tick-output-text')).toBeVisible()
    await expect(output).toHaveScreenshot('ticks-2-output-dark.png')
})

// A long review's diff folded (DIFF_BUDGET in src/lib/review-folds.ts), which review:4's is too short to be: a first
// file fills what the page draws at first, so the second, too long to highlight, shows only the ten lines either side
// of its finding, between two folds, the finding on a line of a thousand characters, its card still the panel's width.
test('a long review diff folded in dark', async ({ page }) => {
    await page.clock.setFixedTime(NOW)
    await storeTheme(page, 'dark')
    await signIn(page)
    const long = `const table = [${'0, '.repeat(330)}0] // a generated table, its line cut at a thousand characters`
    const files = [
        diffFile('src/fills.ts', 1979, (n) => `export const fill${n} = ${n}`),
        diffFile('src/generated/table.ts', 2500, (n) => (n === 1250 ? long : `export const row${n} = ${n}`)),
    ]
    const finding: DiffFinding = {
        severity: 'minor',
        title: 'A generated table edited by hand',
        location: 'src/generated/table.ts:1250',
        detail: 'The table is generated: `make tables` writes it from `data/rows.csv`, so edit that and run it again.',
        file: 1,
        line: 1250,
        dismissed: false,
    }
    await serveReview(page, files, [finding])
    await page.goto('pull-requests/reviews/4')
    await settled(page)
    const panel = page.getByTestId('diff-file').nth(1)
    await expect(panel.getByTestId('diff-fold')).toHaveCount(2)
    await expect(panel).toHaveScreenshot('reviews-folded-dark.png')
})

// Review a PR over a PR's page, opened by R with that PR's URL filled in: the box alone, as the jump palette's.
test('the review dialog in dark', async ({ page }) => {
    await openInDark(page, `pull-requests/pr?url=${encodeURIComponent('https://github.com/acme/web/pull/88')}`)
    await page.keyboard.press('r')
    const dialog = page.getByTestId('review-dialog')
    await expect(dialog.getByLabel('Notes for the reviewer (optional)')).toBeFocused()
    await expect(dialog.getByTestId('review-request-chosen')).toHaveText('in canopy, the default')
    await expect(dialog).toHaveScreenshot('review-dialog-dark.png')
})

// The interface is a quarter larger from a 2560px window. The images are of the operator's window, which already
// uses the width (2xl), so a wider one's would only repeat them larger.
test('the root size grows with the window', async ({ page }) => {
    await page.setViewportSize({ width: 2560, height: 1440 })
    await signIn(page)
    await page.goto('attention')
    await settled(page)
    expect(await page.evaluate(() => getComputedStyle(document.documentElement).fontSize)).toBe('20px')
})

// A narrow window, about the narrowest the UI holds up in (DESIGN.md): the behaviour specs hold that it fits, these
// how it looks. The ticket page whole, for the strip rail, its one column, and the lists in its panels; the tickets,
// PRs, reviews, and worktrees lists for the columns they let go.
test.describe('in a narrow window', () => {
    test.use({ viewport: { width: 820, height: 900 } })

    test('tickets/ABC-102 narrow', async ({ page }) => {
        await openInDark(page, 'tickets/ABC-102')
        await screenshotWhole(page, 'tickets-ABC-102-narrow-dark.png')
    })

    for (const route of ['tickets', 'pull-requests', 'pull-requests/reviews', 'runs/worktrees']) {
        test(`${route} narrow`, async ({ page }) => {
            await openInDark(page, route)
            await screenshotMain(page, `${route.replaceAll('/', '-')}-narrow-dark.png`)
        })
    }
})

// The moment `minutes` before NOW, ISO.
function minutesBefore(minutes: number): string {
    return new Date(NOW.getTime() - minutes * 60_000).toISOString()
}

// Opens `route` in dark, its clock frozen, as every screenshot here is taken.
async function openInDark(page: Page, route: string): Promise<void> {
    await page.clock.setFixedTime(NOW)
    await storeTheme(page, 'dark')
    await signIn(page)
    await page.goto(route)
    await settled(page)
}
