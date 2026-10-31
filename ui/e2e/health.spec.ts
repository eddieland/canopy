import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the nav opens Health under Reports, the week's runs by how they ended", async ({ page }) => {
    await page.goto('reports')
    await settled(page)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Health' }).click()
    await expect(page).toHaveURL(/\/reports\/health$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Health')
    // The mock's week: twenty-five runs ended, a worker's, a review's, and a task's failed (canopy/serve/mock).
    await expect(page.locator('main header p')).toHaveText('3 of 25 runs failed over 7 days')
    await expect(page.getByTestId('health-window-7')).toHaveAttribute('data-state', 'on')
    const failed = page.getByTestId('health-outcome-table').locator('td.text-status-failed')
    await expect(failed).toHaveText(['failed', 'unknown', 'failed'])
    await expect(page.getByTestId('health-unpriced')).toHaveText(
        'No cost reported: 1 of 7 worker runs, 2 of 6 review runs.',
    )
})

test('the failures chart stacks each day by kind, with a table of the same numbers', async ({ page }) => {
    await page.goto('reports/health')
    await settled(page)
    const chart = page.getByTestId('health-chart')
    await expect(chart.getByTestId(/^health-bar-/u)).toHaveCount(7)
    // Today's three failures, a segment for each kind that failed, and its count over its bar.
    await expect(chart.getByTestId(/^health-segment-/u)).toHaveCount(3)
    await expect(chart.getByTestId('health-peak')).toHaveText('3')
    await expect(page.getByTestId('health-legend').getByRole('listitem')).toHaveText([
        'overseer',
        'workers',
        'plans',
        'chores',
        'reviews',
        'tasks',
    ])
    const rows = page.getByTestId('health-table').locator('tbody tr')
    await expect(rows).toHaveCount(7)
    // The newest day first, its failed runs out of its ended ones.
    await expect(rows.first().locator('td').nth(6)).toHaveText('3')
    await expect(rows.first().locator('td').nth(7)).toHaveText('25')
})

test('each failure opens its own page, beside what it was about', async ({ page }) => {
    await page.goto('reports/health')
    await settled(page)
    const failures = page.getByTestId('health-failure-list').getByRole('listitem')
    await expect(failures).toHaveCount(3)
    const worker = page.getByTestId('health-failure-workers-40')
    await expect(worker).toContainText('fix-ci')
    await expect(worker.getByRole('link', { name: 'ABC-100', exact: true })).toBeVisible()
    await expect(page.getByTestId('health-failure-reviews-3').getByRole('link', { name: 'review:3' })).toBeVisible()
    await expect(
        page.getByTestId('health-failure-tasks-2').getByRole('link', { name: 'task:2', exact: true }),
    ).toBeVisible()
    await worker.getByRole('link', { name: 'run:40' }).click()
    await expect(page).toHaveURL(/\/workspace\/runs\/40$/u)
})

test('the window switches to 30 days and back, and the guards say what they refused', async ({ page }) => {
    await page.goto('reports/health')
    await settled(page)
    await expect(page.getByTestId('health-refusal')).toHaveCount(1)
    await expect(page.getByTestId('health-refusal').getByRole('link', { name: 'tick:2' })).toBeVisible()
    await page.getByTestId('health-window-30').click()
    await expect(page).toHaveURL(/\/reports\/health\?days=30$/u)
    await expect(page.locator('main header p')).toHaveText('3 of 46 runs failed over 30 days')
    await expect(page.getByTestId('health-table').locator('tbody tr')).toHaveCount(30)
    // The week, the default, needs no search.
    await page.getByTestId('health-window-7').click()
    await expect(page).toHaveURL(/\/reports\/health$/u)
})

test('a window the page does not offer reads as the week', async ({ page }) => {
    await page.goto('reports/health?days=14')
    await settled(page)
    await expect(page.getByTestId('health-window-7')).toHaveAttribute('data-state', 'on')
    await expect(page.locator('main header p')).toHaveText('3 of 25 runs failed over 7 days')
})
