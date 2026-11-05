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
    const outline = page.getByTestId('epic-outline')
    const r1 = outline.getByText('R1', { exact: true })
    await r1.hover()
    await expect.poll(() => litEntries(page)).toEqual(['entry-B1', 'entry-B3'])
    for (const id of await page.getByText('R1', { exact: true }).all()) {
        await expect(id).toHaveAttribute('data-lit', '')
    }
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

test("a proposed epic's mark opens its plan, read only, and Back returns to the board", async ({ page }) => {
    await page.goto('epics/2')
    await settled(page)
    await page.getByRole('link', { name: 'Open the proposed plan' }).click()
    await expect(page).toHaveURL(/\/epics\/2\/plan$/u)
    await settled(page)
    const plan = page.getByRole('textbox', { name: 'Plan' })
    await expect(plan).toContainText('the copy goes when its customer does')
    await expect(plan).toHaveAttribute('contenteditable', 'false')
    await expect(page.getByRole('heading', { name: 'Comments' })).toHaveCount(0)
    // What changed since the plan the reply replaced is marked as the page opens; the earlier plan stays folded.
    await expect(page.getByRole('button', { name: 'Changes since plan 2' })).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('earlier-plans').getByRole('textbox')).toHaveCount(0)
    await page.getByRole('button', { name: 'Show plan 2' }).click()
    await expect(page.getByTestId('earlier-plans').getByRole('textbox', { name: 'Plan' })).toContainText(
        'Sync on launch and on pull to refresh only.',
    )
    await page.goBack()
    await expect(page).toHaveURL(/\/epics\/2$/u)
    await expect(page.getByTestId('epic-board')).toBeVisible()
})

test("an approved epic's header opens its plan", async ({ page }) => {
    await page.goto('epics/1')
    await settled(page)
    await page.getByRole('link', { name: 'Open plan' }).click()
    await expect(page).toHaveURL(/\/epics\/1\/plan$/u)
    await settled(page)
    await expect(page.getByRole('textbox', { name: 'Plan' })).toContainText('Every billing call goes to v2')
    await expect(
        page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'epic:1' }),
    ).toBeVisible()
})

test('an epic canopy has no record of is missing', async ({ page }) => {
    await page.goto('epics/999')
    await settled(page)
    await expect(page.getByText('canopy has no epic:999')).toBeVisible()
})
