import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the nav opens Connectors under Reports, each source now and the week's runs", async ({ page }) => {
    await page.goto('reports')
    await settled(page)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Connectors' }).click()
    await expect(page).toHaveURL(/\/reports\/connectors$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Connectors')
    // The mock's four days of polls and two ticks' runs, four of them short (canopy/serve/mock/connectors.py).
    await expect(page.locator('main header p')).toHaveText(
        '4 of 388 runs read less than asked over 7 days · jira stale',
    )
    await expect(page.getByTestId('connectors-window-7')).toHaveAttribute('data-state', 'on')
    // jira's latest run asked about two tickets never observed; github's PRs were observed within the half hour.
    await expect(page.getByTestId('connectors-source-jira')).toContainText('2 never observed')
    await expect(page.getByTestId('connectors-source-jira')).toContainText('stale')
    await expect(page.getByTestId('connectors-source-github')).not.toContainText('stale')
    await expect(page.getByTestId('connectors-runs-github').locator('th, td:not([aria-hidden])')).toHaveText([
        'github',
        '194',
        '2',
        '192',
        '192',
        '1',
        '1',
        '1%',
        '32s',
        '44s',
        '2.0m',
        '867 check, 386 pr, 97 review',
        '2 check',
    ])
})

test('the short runs chart stacks each day by source, with a table of the same numbers', async ({ page }) => {
    await page.goto('reports/connectors')
    await settled(page)
    const chart = page.getByTestId('connectors-chart')
    await expect(chart.getByTestId(/^connectors-bar-/u)).toHaveCount(7)
    await expect(chart.getByTestId(/^connectors-segment-/u)).toHaveCount(4)
    await expect(page.getByTestId('connectors-legend').getByRole('listitem')).toHaveText(['jira', 'github'])
    const days = page.getByTestId('connectors-table').locator('tbody tr')
    await expect(days).toHaveCount(7)
    await expect(days.first().locator('td')).toHaveText(['0', '1', '1'])
})

test('the newest short runs say what they missed, and the window switches to 30 days', async ({ page }) => {
    await page.goto('reports/connectors')
    await settled(page)
    const rows = page.getByTestId('connectors-newest-table').getByTestId(/^connectors-run-/u)
    await expect(rows).toHaveCount(4)
    await expect(rows.nth(1)).toContainText('the tracker answered 503 Service Unavailable')
    await expect(rows.nth(2)).toContainText('it did not finish in 2 minutes')
    await expect(page.getByTestId('connectors-refusal')).toHaveCount(2)
    await page.getByTestId('connectors-window-30').click()
    await expect(page).toHaveURL(/\/reports\/connectors\?days=30$/u)
    await expect(page.getByTestId('connectors-table').locator('tbody tr')).toHaveCount(30)
})
