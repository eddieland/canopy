import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import {
    diffFile,
    holdAttentionList,
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
            if (route === 'tickets/ABC-101') {
                // Its conversation ends on the run working it, which the stream's runs bring in after the page.
                await expect(page.getByTestId('working-41')).toBeVisible()
            }
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
        await page.goto('workspace/runs/39')
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
        await page.goto('workspace/runs/39')
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
        await page.goto('workspace/ticks/2')
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
        // Each title fills in once the tickets load: under load, the box was taken with both still untitled.
        await expect(palette.getByRole('option', { name: /Debounce search input/u })).toBeVisible()
        await expect(palette.getByRole('option', { name: /Schedule report exports/u })).toBeVisible()
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

// The true all clear, which the mock's journal, with its items, never shows: the list reads empty, and the stream,
// which would send it again whole, keeps what else it says. Its main pane alone, the digest over the void it fills.
test('the all-clear digest in dark', async ({ page }) => {
    await page.clock.setFixedTime(NOW)
    await storeTheme(page, 'dark')
    await signIn(page)
    await page.route('**/api/attention', (route) => route.fulfill({ json: [] }))
    await holdAttentionList(page)
    await page.goto('attention')
    await settled(page)
    await expect(page.getByTestId('all-clear-today')).toBeVisible()
    await expect(page.getByTestId('all-clear-working')).toBeVisible()
    await screenshotMain(page, 'attention-all-clear-dark.png')
})

// Every palette but a theme's default sets the neutrals, the accent, and its corners, edges, depth, and face, all of
// which one page's panels show: its main pane alone, so a change to the header or the rail rewrites none of these.
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

// A palette that gives the shell a form of its own, its aurora, name, and nav highlight: the whole page, so the header
// and the rail show. Pulp's in light as well, whose name plate and aurora are inked otherwise.
for (const [theme, palette] of [
    ['dark', 'gruvbox'],
    ['dark', 'black'],
    ['dark', 'pulp'],
    ['light', 'pulp'],
] as const) {
    test(`the shell in ${palette} ${theme}`, async ({ page }) => {
        await page.clock.setFixedTime(NOW)
        await storeTheme(page, theme)
        await storePalette(page, theme, palette)
        await signIn(page)
        await page.goto('tickets/ABC-102')
        await settled(page)
        await expect(page.locator('html')).toHaveAttribute(`data-${theme}-palette`, palette)
        await screenshotWhole(page, `shell-${palette}-${theme}.png`)
    })
}

// A worker's report in Markdown, its inline code, heading, list, and fence, on Gruvbox dark: the palette that sets
// every line in mono, where code drawn smaller than its line or on a tile darker than its bubble read worst (#1838).
// The conversation alone, so a change elsewhere on the ticket's page rewrites none of it.
test('rich text in a conversation in gruvbox dark', async ({ page }) => {
    await page.clock.setFixedTime(NOW)
    await storeTheme(page, 'dark')
    await storePalette(page, 'dark', 'gruvbox')
    await signIn(page)
    await page.goto('tickets/ABC-103')
    await settled(page)
    await expect(page.locator('html')).toHaveAttribute('data-dark-palette', 'gruvbox')
    const conversation = page.getByTestId('conversation')
    await expect(conversation.getByText('What changed', { exact: true })).toBeVisible()
    await expect(conversation).toHaveScreenshot('conversation-rich-text-gruvbox-dark.png')
})

// A conversation in Pulp dark, whose bubbles grow a balloon tail: every kind of message, on both sides, so each tail
// shows over its own fill, the operator's dropping its shadow outward. The conversation alone.
test('balloon tails in a conversation in pulp dark', async ({ page }) => {
    await page.clock.setFixedTime(NOW)
    await storeTheme(page, 'dark')
    await storePalette(page, 'dark', 'pulp')
    await signIn(page)
    await page.goto('tickets/ABC-103')
    await settled(page)
    await expect(page.locator('html')).toHaveAttribute('data-dark-palette', 'pulp')
    const conversation = page.getByTestId('conversation')
    await expect(conversation.getByText('What changed', { exact: true })).toBeVisible()
    await expect(conversation).toHaveScreenshot('conversation-pulp-dark.png')
    // The tails stay inside the thread's padding: it never scrolls sideways.
    const thread = page.getByTestId('thread-scroll')
    expect(await thread.evaluate((region) => region.scrollWidth - region.clientWidth)).toBe(0)
})

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
    await page.goto('workspace/ticks/2')
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
    await expect(dialog.getByTestId('review-request-ref')).toHaveText('acme/web#88')
    await expect(dialog.getByRole('button', { name: 'Persona: canopy (default)' })).toBeEnabled()
    await expect(dialog.getByTestId('review-model-default')).toBeVisible()
    await expect(dialog).toHaveScreenshot('review-dialog-dark.png')
})

// The review dialog with a model picked for this request alone, which its menu then names.
test('the review dialog with a model chosen in dark', async ({ page }) => {
    await openInDark(page, `pull-requests/pr?url=${encodeURIComponent('https://github.com/acme/web/pull/88')}`)
    await page.keyboard.press('r')
    const dialog = page.getByTestId('review-dialog')
    await dialog.getByRole('button', { name: 'Model: default' }).click()
    await page.getByRole('option', { name: 'anthropic/claude-opus-4-1@max' }).click()
    await expect(dialog.getByRole('button', { name: 'Model: anthropic/claude-opus-4-1@max' })).toBeVisible()
    await expect(dialog).toHaveScreenshot('review-dialog-model-dark.png')
})

// Start a ticket over the attention page, opened by T: the box alone, as the review dialog's.
test('the ticket dialog in dark', async ({ page }) => {
    await openInDark(page, 'attention')
    await page.keyboard.press('t')
    const dialog = page.getByTestId('ticket-dialog')
    await expect(dialog.getByLabel('Ticket key')).toBeFocused()
    await expect(dialog).toHaveScreenshot('ticket-dialog-dark.png')
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

// Loop settings with changes waiting: the rows marked, and the save bar listing them, with the one-way warning a
// stricter change brings. Typed, never saved: the root server's journal and config never change.
test('settings/limits with changes waiting', async ({ page }) => {
    await openInDark(page, 'settings/limits')
    const form = page.getByTestId('config-form')
    await form.getByTestId('capacity.max_workers').fill('4')
    await form.getByTestId('trust.trusted_reviewers-lint-bot').click()
    await expect(form.getByTestId('config-pending')).toHaveText('2 unsaved changes')
    await screenshotMain(page, 'settings-limits-changed-dark.png')
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

    for (const route of ['tickets', 'pull-requests', 'pull-requests/reviews', 'workspace/worktrees']) {
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
