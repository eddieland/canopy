import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// A transcript at the server's bounds is the longest the page is ever sent: 2,000 entries and 2,000,000 characters
// (canopy/core/transcript.py), a month-long worker's or overseer's session. Drawn whole, its rows were 80,000 elements,
// and each key typed in Find waited on all of them; the page draws 100 rows at first and a fold shows 100 more a click
// (TRANSCRIPT_BUDGET in src/lib/transcript.ts).
const MAX_ENTRIES = 2000
const CALLS = 100
const TOOLS_PER_CALL = MAX_ENTRIES / CALLS - 2
const PAGE_ROWS = 100
const STEP = 100
// The elements the whole page may hold before a fold is opened: the rail, the header, the Run panel, the context
// chart, and the rows drawn.
const MAX_ELEMENTS = 10_000

const START = Date.parse('2026-10-08T09:00:00Z')

/** A transcript of `MAX_ENTRIES` entries, each model call what the agent said, its tool calls, and its end. */
function longSession() {
    const entries: Record<string, unknown>[] = []
    let second = 0
    const at = () => new Date(START + 1000 * (second += 3)).toISOString()
    for (let c = 1; c <= CALLS; c++) {
        const said =
            c === CALLS ? 'Last, the kingfisher test, then the PR.' : `Part ${c}: the next file, then its tests.`
        entries.push({ kind: 'text', call: c, at: at(), text: said, reasoning: false, cut: false })
        for (let t = 0; t < TOOLS_PER_CALL; t++) {
            const command = `npm test -- part-${c}-${t}`
            // What a test run prints, about 900 characters of it.
            const output = Array.from({ length: 12 }, (_, l) => `  ✓ part ${c} case ${t}.${l} passes in ${l + 3}ms`)
                .join('\n')
                .padEnd(900, '.')
            entries.push({
                kind: 'tool',
                call: c,
                at: at(),
                tool: 'bash',
                title: `Runs part ${c}'s tests`,
                input: JSON.stringify({ command, description: `Runs part ${c}'s tests` }, null, 2),
                output,
                status: 'completed',
                duration_ms: 1200,
                cut: false,
            })
        }
        const split = { input: 2000, cache_read: 20_000 + 100 * c, cache_write: 300, output: 400, reasoning: 0 }
        entries.push({ kind: 'step', call: c, at: at(), reason: 'tool-calls', split, tokens: 22_700, cost_usd: 0.03 })
    }
    expect(entries).toHaveLength(MAX_ENTRIES)
    return entries
}

/** Serves run:39's transcript as the long session, the rest of it as the mock journal has it. */
async function serveLongSession(page: Page): Promise<void> {
    const entries = longSession()
    await page.route('**/api/runs/39/transcript', async (route) => {
        const response = await route.fetch()
        const body = (await response.json()) as Record<string, unknown>
        await route.fulfill({ response, json: { ...body, entries, truncated: true } })
    })
}

test.beforeEach(async ({ page }) => {
    await signIn(page)
    await serveLongSession(page)
})

test('a transcript as long as the server sends draws a page of rows, and a fold shows more', async ({ page }) => {
    await page.goto('workspace/runs/39')
    await settled(page)
    const transcript = page.getByTestId('transcript')
    const rows = transcript.getByTestId('transcript-entries').locator(':scope > li')
    await expect(rows).toHaveCount(PAGE_ROWS + 1)
    expect(await page.evaluate(() => document.querySelectorAll('*').length)).toBeLessThan(MAX_ELEMENTS)

    // The fold says how many rows it holds back, and shows the next of them.
    const fold = transcript.getByTestId('transcript-fold')
    await expect(fold).toHaveText(`Show ${STEP} of 1,900 more rows`)
    await fold.getByRole('button').click()
    await expect(rows).toHaveCount(PAGE_ROWS + STEP + 1)
    await expect(fold).toHaveText(`Show ${STEP} of 1,800 more rows`)

    // All open opens the tool calls drawn, the first ten model calls' 18 each, and no more.
    const drawnTools = ((PAGE_ROWS + STEP) / (TOOLS_PER_CALL + 2)) * TOOLS_PER_CALL
    await expect(transcript.getByTestId('transcript-tool')).toHaveCount(drawnTools)
    await transcript.getByRole('button', { name: 'All open' }).click()
    await expect(transcript.locator('details[open]')).toHaveCount(drawnTools)
})

test('Find finds a row the page has not drawn', async ({ page }) => {
    await page.goto('workspace/runs/39')
    await settled(page)
    const transcript = page.getByTestId('transcript')
    const rows = transcript.getByTestId('transcript-entries').locator(':scope > li')
    await expect(rows).toHaveCount(PAGE_ROWS + 1)
    await expect(transcript).not.toContainText('kingfisher')

    const find = transcript.getByRole('searchbox', { name: 'Find lines in the transcript' })
    await find.fill('KINGFISHER')
    await expect(transcript.getByTestId('transcript-found')).toHaveText('1 line, 1 row')
    await expect(rows).toHaveCount(1)
    await expect(transcript.locator('mark')).toHaveText('kingfisher')

    // A search that finds more than a page draws a page of them, the fold counting the rest.
    await find.fill('passes in 3ms')
    await expect(transcript.getByTestId('transcript-found')).toHaveText('1800 lines, 1800 rows')
    await expect(rows).toHaveCount(PAGE_ROWS + 1)
    await expect(transcript.getByTestId('transcript-fold')).toHaveText(`Show ${STEP} of 1,700 more rows`)
})

test("the context chart's row is drawn before it is shown, wherever the budget left it", async ({ page }) => {
    await page.goto('workspace/runs/39')
    await settled(page)
    const transcript = page.getByTestId('transcript')
    const context = transcript.getByTestId('transcript-context')
    // The chart is folded to its line on arrival; its bars pick the call.
    await context.getByRole('button', { name: 'Show chart' }).click()
    // The last call's largest addition is a tool call of call 99, past the page's first rows.
    await context
        .getByRole('radiogroup', { name: 'Model calls' })
        .getByRole('radio', { name: /^call 100:/u })
        .click()
    await transcript.getByTestId('context-grew').getByRole('button').first().click()
    const shown = transcript.locator('details[open]')
    await expect(shown).toHaveCount(1)
    await expect(shown.locator('summary')).toContainText('part-99-')
    await expect(shown.locator('summary')).toBeFocused()
    await expect(shown.locator('summary')).toBeInViewport()
})

test('a search redraws the rows without cross-fading the page, and loses no key typed', async ({ page }) => {
    // Counts the view transitions the page starts: React starts one for a transition the outlet cross-fades.
    await page.addInitScript(() => {
        const counted = globalThis as typeof globalThis & { viewTransitions: number }
        const start = document.startViewTransition.bind(document)
        counted.viewTransitions = 0
        document.startViewTransition = (update) => {
            counted.viewTransitions += 1
            return start(update)
        }
    })
    await page.goto('workspace/runs/39')
    await settled(page)
    const transcript = page.getByTestId('transcript')
    const find = transcript.getByRole('searchbox', { name: 'Find lines in the transcript' })

    // Typed key by key, as the operator does: each key redraws the rows behind the field. Cross-faded, keys were lost.
    await find.pressSequentially('kingfisher', { delay: 100 })
    await expect(find).toHaveValue('kingfisher')
    await expect(transcript.getByTestId('transcript-found')).toHaveText('1 line, 1 row')
    const started = await page.evaluate(
        () => (globalThis as typeof globalThis & { viewTransitions: number }).viewTransitions,
    )
    expect(started).toBe(0)
})
