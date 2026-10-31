import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the nav opens CI under Reports, the week's checks the worst first", async ({ page }) => {
    await page.goto('reports')
    await settled(page)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'CI', exact: true }).click()
    await expect(page).toHaveURL(/\/reports\/ci$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('CI')
    // The mock's week: ten heads first checked, four green first time, and kicks off (canopy/serve/mock/ci.py).
    await expect(page.locator('main header p')).toHaveText(
        '40% of PR heads green first time · no flaky kicks over 7 days',
    )
    await expect(page.getByTestId('ci-window-7')).toHaveAttribute('data-state', 'on')
    const rows = page.getByTestId('ci-check-table').getByTestId('ci-check')
    await expect(rows).toHaveCount(7)
    await expect(rows.first().locator('th, td')).toHaveText(['e2e', '6', '3', '60%', '1 of 1'])
    await expect(page.getByTestId('ci-limits')).toContainText('A commit status has no check run')
})

test('the red checks chart stacks each day by check, with a table of the same numbers', async ({ page }) => {
    await page.goto('reports/ci')
    await settled(page)
    const chart = page.getByTestId('ci-chart')
    await expect(chart.getByTestId(/^ci-bar-/u)).toHaveCount(7)
    // Today's five red runs: e2e's three, integration's, and typecheck's among the rest.
    await expect(chart.getByTestId('ci-peak')).toHaveText('5')
    await expect(chart.getByTestId(/^ci-segment-/u)).toHaveCount(6)
    await expect(page.getByTestId('ci-legend').getByRole('listitem')).toHaveText([
        'e2e',
        'unit',
        'build',
        'integration',
        'other',
    ])
    const days = page.getByTestId('ci-table').locator('tbody tr')
    await expect(days).toHaveCount(7)
    await expect(days.first().locator('td').last()).toHaveText('5')
})

test('a fix says how its red checks ran on the next head, and kicks say they are off', async ({ page }) => {
    await page.goto('reports/ci')
    await settled(page)
    const old = page.getByTestId('ci-fix-40')
    await expect(old.getByTestId('ci-fixed')).toContainText('e2e')
    await expect(old.getByTestId('ci-fixed')).toContainText('not yet')
    await expect(page.getByTestId('ci-fix-43')).toContainText('no red check observed when it started')
    await expect(page.getByTestId('ci-kicks')).toContainText('kicks are off: trust.max_flaky_kicks is 0')
    await old.getByRole('link', { name: 'run:40' }).click()
    await expect(page).toHaveURL(/\/runs\/40$/u)
})

test('the window switches to 30 days, and the cooldown points to Health', async ({ page }) => {
    await page.goto('reports/ci')
    await settled(page)
    await page.getByTestId('ci-window-30').click()
    await expect(page).toHaveURL(/\/reports\/ci\?days=30$/u)
    await expect(page.locator('main header p')).toHaveText(
        '40% of PR heads green first time · no flaky kicks over 30 days',
    )
    await expect(page.getByTestId('ci-table').locator('tbody tr')).toHaveCount(30)
    await page.getByTestId('ci-cooldown-line').getByRole('link', { name: 'Health' }).click()
    await expect(page).toHaveURL(/\/reports\/health\?days=30$/u)
})
