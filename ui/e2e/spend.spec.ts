import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the rail's counters open the spend page, whose total agrees with the 30 days'", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const month = await page.getByTestId('rail-spend-30d').textContent()

    await page.getByTestId('rail-spend-link-24h').click()
    await expect(page).toHaveURL(/\/spend$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Spend')
    await expect(page.getByTestId('spend-window-7')).toHaveAttribute('data-state', 'on')
    await expect(page.getByTestId('spend-chart').getByTestId(/^spend-bar-/u)).toHaveCount(7)

    await page.goto('attention')
    await page.getByTestId('rail-spend-link-30d').click()
    await expect(page).toHaveURL(/\/spend\?days=30$/u)
    await expect(page.getByTestId('spend-window-30')).toHaveAttribute('data-state', 'on')
    await expect(page.getByTestId('spend-chart').getByTestId(/^spend-bar-/u)).toHaveCount(30)
    // Every run in the mock journal started within the 30 days, so the window's total is the rail's.
    await expect(page.getByTestId('spend-total-total')).toHaveText(month ?? '')
})

test('the window switches from the toggle, and idle spend is its own series with its ticks linked', async ({
    page,
}) => {
    await page.goto('spend?days=30')
    await settled(page)
    await page.getByTestId('spend-window-7').click()
    await expect(page).toHaveURL(/\/spend$/u)
    await expect(page.getByTestId('spend-table').locator('tbody tr')).toHaveCount(7)

    // The mock's second tick was idle: its overseer's cost is the idle series, and the share of the overseer's.
    await expect(page.getByTestId('spend-total-idle')).toHaveText('$0.31')
    await expect(page.getByTestId('spend-total-overseer')).toHaveText('$0.59')
    await expect(page.getByTestId('spend-idle-share')).toContainText('53%')
    await expect(page.getByTestId('spend-groups-idle')).toContainText('1')
    await expect(page.getByTestId('spend-woken-table-timer')).toBeVisible()
    const today = page.getByTestId('spend-day-2026-10-08')
    await expect(today.locator('td').first()).toHaveText('$0.31')

    const ticks = page.getByTestId('spend-idle-tick-list')
    await expect(ticks.getByTestId(/^tick-\d+$/u)).toHaveCount(1)
    await ticks.getByRole('link', { name: 'tick:2' }).click()
    await expect(page).toHaveURL(/\/ticks\/2$/u)
})

test('a window the page does not offer reads as the week', async ({ page }) => {
    await page.goto('spend?days=9')
    await settled(page)
    await expect(page.getByTestId('spend-window-7')).toHaveAttribute('data-state', 'on')
    await expect(page.getByTestId('spend-table').locator('tbody tr')).toHaveCount(7)
})

test('the nav opens the spend page on the week, its item marked', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const nav = page.getByRole('navigation', { name: 'Main' })
    await nav.getByRole('link', { name: 'Spend' }).click()
    await expect(page).toHaveURL(/\/spend$/u)
    await expect(page.getByTestId('spend-window-7')).toHaveAttribute('data-state', 'on')
    await expect(nav.getByRole('link', { name: 'Spend' })).toHaveAttribute('data-status', 'active')
    await expect(page.getByTestId('nav-highlight')).toHaveClass(/\bbg-section-spend\/16\b/u)
})

test("30 days' table scrolls in its panel under its column names, and a week's shows whole", async ({ page }) => {
    await page.goto('spend?days=30')
    await settled(page)
    const region = page.getByTestId('spend-table-scroll')
    await expect(page.getByTestId('spend-table').locator('tbody tr')).toHaveCount(30)
    const scrolls = () => region.evaluate((el) => el.scrollHeight > el.clientHeight)
    expect(await scrolls()).toBe(true)

    // Scrolled to the oldest day, the column names stay at the region's top. Within a pixel: a sticky header lands on a
    // fraction of one that differs between runs, and once missed the half pixel `toBeCloseTo(y, 0)` allows by 0.02.
    await region.evaluate((el) => el.scrollTo({ top: el.scrollHeight }))
    const thead = page.getByTestId('spend-table').locator('thead')
    await expect
        .poll(async () => {
            const [head, box] = await Promise.all([thead.boundingBox(), region.boundingBox()])
            return Math.abs((head?.y ?? Number.NaN) - (box?.y ?? Number.NaN))
        })
        .toBeLessThanOrEqual(1)

    await page.getByTestId('spend-window-7').click()
    await expect(page.getByTestId('spend-table').locator('tbody tr')).toHaveCount(7)
    expect(await scrolls()).toBe(false)
})

test("the ticket, PR, and tool tables scroll under their column names, flush with the panel's title", async ({
    page,
}) => {
    await page.goto('spend')
    await settled(page)
    for (const id of ['spend-ticket-table', 'spend-pull-request-table', 'spend-tool-table']) {
        const table = page.getByTestId(id)
        const region = page.getByRole('region').filter({ has: table })
        // The mock's rows fit their regions: shorten one until it scrolls, then scroll it to its end.
        await region.evaluate((el) => {
            el.style.maxHeight = '6rem'
            el.scrollTo({ top: el.scrollHeight })
        })
        // Within a pixel, as the day table's: no strip of the padded region over the names for the rows to show in.
        await expect
            .poll(async () => {
                const [head, box] = await Promise.all([table.locator('thead').boundingBox(), region.boundingBox()])
                return Math.abs((head?.y ?? Number.NaN) - (box?.y ?? Number.NaN))
            })
            .toBeLessThanOrEqual(1)
    }
})

test("each ticket's and PR's own runs, the costliest first, open their pages beside the tickets done", async ({
    page,
}) => {
    await page.goto('spend')
    await settled(page)
    // The mock journal marks no ticket done, so there is nothing to divide the spend by.
    await expect(page.getByTestId('spend-done')).toHaveText('0')
    await expect(page.getByTestId('spend-per-done')).toHaveText('–')
    await expect(page.getByTestId('spend-day-2026-10-08').locator('td').last()).toHaveText('0')

    const tickets = page.getByTestId('spend-ticket-table').locator('tbody tr')
    await expect(tickets).toHaveCount(7)
    // ABC-099's run and the two reviews of its PR.
    await expect(tickets.first()).toHaveAttribute('data-testid', 'spend-ticket-ABC-099')
    await expect(tickets.first().locator('td').nth(1)).toHaveText('$2.76')

    const prs = page.getByTestId('spend-pull-request-table').getByTestId('spend-pull-request')
    await expect(prs).toHaveCount(4)
    await expect(prs.last()).toContainText('none')
    await prs.first().getByRole('link', { name: 'acme/web#88', exact: true }).click()
    await expect(page).toHaveURL(/\/pull-requests\/pr\?url=/u)
})

test('the tools whose calls returned the most, by kind, the most first', async ({ page }) => {
    await page.goto('spend')
    await settled(page)
    const tools = page.getByTestId('spend-tool-table').getByTestId('spend-tool')
    await expect(tools).toHaveCount(11)
    // The overseer's PR reads over both mock ticks, then the workers' shell calls.
    await expect(tools.first().getByRole('cell')).toHaveText(['overseer', '25', '0', '325.0k', '81.3k'])
    await expect(tools.first().getByRole('rowheader')).toHaveText('github_pull_request_read')
    await expect(tools.nth(1).getByRole('rowheader')).toHaveText('bash')
    await expect(tools.nth(1).getByRole('cell')).toHaveText(['workers', '119', '11', '279.0k', '69.8k'])
})
