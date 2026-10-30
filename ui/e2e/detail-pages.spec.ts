import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// A run's, a tick's, a chore run's, and a task run's pages share one skeleton (ui/DESIGN.md, "A detail page has one
// skeleton"): the header says what it is and its state, the identity panel leads with its summary, and each fact is
// said once.

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("a run's state, kind, ticket, and title are each said once above its transcript", async ({ page }) => {
    await page.goto('runs/39')
    await settled(page)
    const above = await textAboveTranscript(page)
    // The key, but not the branch named for it.
    for (const fact of [/\bdone\b/gu, /\bimplement\b/gu, /ABC-099(?!-)/gu, /Debounce search input/gu]) {
        expect(above.match(fact)?.length ?? 0, `${String(fact)} in ${above}`).toBe(1)
    }
    // The key is the description's, and opens the ticket.
    await expect(page.locator('main header').getByRole('link', { name: 'ABC-099', exact: true })).toHaveAttribute(
        'href',
        /\/tickets\/ABC-099$/u,
    )
})

test("a run's and a review's pages show the persona each wrote in, with the start of its digest", async ({ page }) => {
    await page.goto('runs/39')
    await settled(page)
    await expect(page.getByRole('definition').filter({ hasText: /^canopy c4a0f1e2d3b4$/u })).toBeVisible()
    // ABC-099's reviewer was set to skeptic from its page; its latest review wrote in it.
    await page.goto('pull-requests/reviews/4')
    await settled(page)
    await expect(page.getByRole('definition').filter({ hasText: /^skeptic 5e7a1c2b3d4e$/u })).toBeVisible()
    await page.goto('tickets/ABC-099')
    await settled(page)
    await expect(page.getByRole('button', { name: 'reviewer persona: skeptic' })).toBeVisible()
    await expect(page.getByTestId('ticket-agents')).toContainText("this ticket's override")
})

test("a chore run's chore is the trail's link alone, and a tick's output path the Output panel's", async ({ page }) => {
    await page.goto('chores/deps/runs/2')
    await settled(page)
    await expect(page.locator('main').getByRole('link', { name: 'chore:deps', exact: true })).toHaveCount(1)
    await expect(
        page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'chore:deps' }),
    ).toBeVisible()

    await page.goto('runs/ticks/2')
    await settled(page)
    await expect(page.locator('main').getByText('.canopy/ticks/2.log')).toHaveCount(1)
    await expect(page.getByTestId('tick-output')).toContainText('.canopy/ticks/2.log')
})

test('each page leads with its summary, says how long it ran, and names its session over its transcript', async ({
    page,
}) => {
    const pages: [string, string][] = [
        ['runs/39', 'ses_mock39'],
        ['runs/ticks/2', 'ses_tick2'],
        ['chores/deps/runs/2', 'ses_chore2'],
        ['tasks/1/runs/1', 'ses_task1'],
    ]
    for (const [path, session] of pages) {
        await page.goto(path)
        await settled(page)
        const fields = page.locator('main dl').first()
        await expect(fields.getByRole('term').first(), path).toHaveText('summary')
        // Started, ended, and how long it took, as one field.
        await expect(fields.getByRole('definition').filter({ hasText: '→' }), path).toContainText(/ · \d+[smhd]/u)
        await expect(fields.getByTitle('how long it ran'), path).toBeVisible()
        await expect(page.getByTestId('transcript'), path).toContainText(`session ${session}`)
        await expect(page.locator('main').getByText(`session ${session}`), path).toHaveCount(1)
    }
})

test("a run's memory arrives folded to its header", async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 1000 })
    await page.goto('runs/40')
    await settled(page)
    const memory = page.getByTestId('run-memory')
    await expect(memory.getByRole('button', { name: 'Show memory' })).toHaveAttribute('aria-expanded', 'false')
    const folded = await memory.boundingBox()
    expect(folded?.height).toBeLessThanOrEqual(40)

    // Open, it is its rows' height again: what folding it saves the page.
    await memory.getByRole('button', { name: 'Show memory' }).click()
    await expect(memory.getByTestId('memory-2')).toBeVisible()
    const open = await memory.boundingBox()
    expect((open?.height ?? 0) - (folded?.height ?? 0)).toBeGreaterThan(200)
})

/**
 * The text of the page's main pane above its transcript, its header and the panels before it, a line a text node, so
 * words in neighbouring elements stay apart.
 */
function textAboveTranscript(page: Page): Promise<string> {
    return page.locator('main').evaluate((main) => {
        const transcript = main.querySelector('[data-testid=transcript]')
        const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT)
        const texts: string[] = []
        for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
            // In document order, so the transcript's first text is where what is above it ends.
            if (transcript?.contains(node) === true) {
                break
            }
            texts.push(node.textContent ?? '')
        }
        return texts.join('\n')
    })
}
