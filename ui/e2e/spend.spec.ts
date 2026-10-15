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

test("30 days' table scrolls in its panel under its column names, and a week's shows whole", async ({ page }) => {
    await page.goto('spend?days=30')
    await settled(page)
    const region = page.getByTestId('spend-table-scroll')
    await expect(page.getByTestId('spend-table').locator('tbody tr')).toHaveCount(30)
    const scrolls = () => region.evaluate((el) => el.scrollHeight > el.clientHeight)
    expect(await scrolls()).toBe(true)

    // Scrolled to the oldest day, the column names stay at the region's top.
    await region.evaluate((el) => el.scrollTo({ top: el.scrollHeight }))
    const head = await page.getByTestId('spend-table').locator('thead').boundingBox()
    const box = await region.boundingBox()
    expect(head?.y).toBeCloseTo(box?.y ?? Number.NaN, 0)

    await page.getByTestId('spend-window-7').click()
    await expect(page.getByTestId('spend-table').locator('tbody tr')).toHaveCount(7)
    expect(await scrolls()).toBe(false)
})
