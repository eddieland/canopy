import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the nav opens Plans under Reports, September's plans split by level", async ({ page }) => {
    await page.goto('reports')
    await settled(page)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Plans', exact: true }).click()
    await expect(page).toHaveURL(/\/reports\/plans$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Plans')
    // The mock's 30 days: September's planned tickets, at off and strict, and ABC-105's two (canopy/serve/mock/).
    await expect(page.locator('main header p')).toHaveText(
        '8 plans · 5 approved, 2 by the planner · 2 of 5 PRs needed a resume over 30 days',
    )
    await expect(page.getByTestId('plans-window-30')).toHaveAttribute('data-state', 'on')
    await expect(page.getByTestId('plans-group-table').getByTestId('plans-group')).toHaveCount(4)
    await expect(page.getByTestId('plans-length-table').getByTestId('plans-length')).toHaveCount(2)
    await expect(page.getByTestId('plans-key')).toContainText('policy.planner_may_approve is off now.')
})

test('90 days reach the plan written before canopy kept its level, and a plan opens its run', async ({ page }) => {
    await page.goto('reports/plans')
    await settled(page)
    await page.getByTestId('plans-window-90').click()
    await expect(page).toHaveURL(/\/reports\/plans\?days=90$/u)
    await expect(page.getByTestId('plans-group-table').getByTestId('plans-group')).toHaveCount(5)
    await expect(page.getByTestId('plans-group-table')).toContainText('not recorded')
    await page.getByTestId('plans-plan-7').getByRole('link', { name: /^run:/u }).click()
    await expect(page).toHaveURL(/\/runs\/\d+$/u)
})
