import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// An epic's page (ui/DESIGN.md, "An epic"), over the mock journal's epics: epic 1 approved, with members; epic 2
// proposed, after a reply; epic 3 just submitted, its plan run at work.

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

/** The board's entries that are lit now, by id. */
function litEntries(page: Page): Promise<string[]> {
    return page
        .getByTestId(/^entry-B\d+$/u)
        .evaluateAll((rows) =>
            rows
                .filter((row) => row instanceof HTMLElement && row.dataset.lit !== undefined)
                .map((row) => (row as HTMLElement).dataset.testid ?? ''),
        )
}

/** The board's entries lit now, and whether each place `id` shows is lit, read at one instant. */
function lit(page: Page, id: string): Promise<{ entries: string[]; id: boolean[] }> {
    return page.evaluate((name) => {
        const entries = [...document.querySelectorAll<HTMLElement>('[data-testid^="entry-B"]')]
            .filter((row) => row.dataset.lit !== undefined)
            .map((row) => row.dataset.testid ?? '')
        const ids = [...document.querySelectorAll<HTMLElement>('main span')]
            .filter((span) => span.textContent === name && span.children.length === 0)
            .map((span) => span.dataset.lit !== undefined)
        return { entries, id: ids }
    }, id)
}

test("the list opens an epic's page, which leads with its breakdown beside its members", async ({ page }) => {
    await page.goto('epics')
    await settled(page)
    await page.getByTestId('epic-1').getByRole('link', { name: 'epic:1', exact: true }).click()
    await expect(page).toHaveURL(/\/epics\/1$/u)
    await settled(page)
    const b1 = page.getByTestId('entry-B1')
    await expect(b1.getByRole('link', { name: 'ABC-103', exact: true })).toHaveAttribute('href', /\/tickets\/ABC-103$/u)
    await expect(page.getByTestId('entry-B3')).toContainText('none yet')
    await expect(
        page.getByTestId('members-of-no-entry').getByRole('link', { name: 'ABC-100', exact: true }),
    ).toBeVisible()
})

test('pointing at a requirement lights the entries that cover it, and the id wherever it shows', async ({ page }) => {
    await page.goto('epics/1')
    await settled(page)
    // Each member's link out comes with the server's meta, after the page, and widens the board as it comes: hovered
    // before it, the board could move from under the mouse.
    await expect(page.getByRole('link', { name: 'ABC-103 in the tracker' })).toBeVisible()
    const outline = page.getByTestId('epic-outline')
    const r1 = outline.getByText('R1', { exact: true })
    await r1.hover()
    // The entries and the id are read at one instant, so they are told lit by the same pointing.
    await expect.poll(() => lit(page, 'R1')).toEqual({ entries: ['entry-B1', 'entry-B3'], id: [true, true, true] })
    // Lighting only adds: every entry still reads as it did, its members and none yet among them.
    await expect(page.getByTestId('entry-B2').getByRole('link', { name: 'ABC-104', exact: true })).toBeVisible()
    await expect(page.getByTestId('entry-B4')).toContainText('none yet')
    await page.getByRole('heading', { level: 1 }).hover()
    await expect.poll(() => litEntries(page)).toEqual([])
})

test('a contract lit from the keyboard lights who provides it and who uses it', async ({ page }) => {
    await page.goto('epics/1')
    await settled(page)
    await page.getByTestId('entry-B2').getByText('C1', { exact: true }).focus()
    await expect.poll(() => litEntries(page)).toEqual(['entry-B1', 'entry-B2', 'entry-B3'])
    await expect(page.getByTestId('epic-outline').getByText('C1', { exact: true })).toHaveAttribute('data-lit', '')
    // Its tip says its words, as the planner wrote them.
    await expect(page.getByRole('tooltip')).toContainText('BillingClient')
    await page.keyboard.press('Tab')
    await expect(page.getByTestId('epic-outline').getByText('C1', { exact: true })).not.toHaveAttribute('data-lit')
})

test("a proposed epic's board is marked proposed, and a planning one names its plan run", async ({ page }) => {
    await page.goto('epics/2')
    await settled(page)
    await expect(page.getByTestId('epic-board').getByText('proposed', { exact: true })).toBeVisible()
    await page.goto('epics/3')
    await settled(page)
    await expect(page.getByTestId('plan-run-working')).toContainText('epic:3#4 is writing its plan')
})

test('an epic canopy has no record of is missing', async ({ page }) => {
    await page.goto('epics/999')
    await settled(page)
    await expect(page.getByText('canopy has no epic:999')).toBeVisible()
})
