import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('the nav opens Reports on its cards, then the months since the workspace began, the latest in detail', async ({
    page,
}) => {
    await page.goto('attention')
    await settled(page)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Reports' }).click()
    await expect(page).toHaveURL(/\/reports$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Reports')
    // A card for each page under Reports, each its page's line over 30 days.
    const cards = page.getByRole('navigation', { name: 'Report pages' }).getByRole('link')
    await expect(cards).toHaveCount(6)
    await expect(page.getByTestId('reports-card-spend-line')).toHaveText(/ over 30 days · /u)
    await expect(page.getByTestId('reports-card-health-line')).toHaveText(/ over 30 days$/u)
    // The mock's workspace took canopy up in April: the page opens there, no span pressed.
    await expect(page.getByTestId('reports-months-span')).toHaveText('since April 2026')
    await expect(page.getByTestId('reports-span-12')).toHaveAttribute('data-state', 'off')
    await expect(page.getByTestId('reports-chart').getByTestId(/^reports-bar-/u)).toHaveCount(7)
    await expect(page.getByTestId('reports-bar-2026-10')).toHaveAttribute('data-marked', 'true')
    const months = page.getByTestId('reports-month')
    await expect(months).toHaveCount(7)
    await expect(months.first().getByRole('rowheader')).toHaveText('Oct 2026')
    await expect(months.last().getByRole('rowheader')).toHaveText('Apr 2026')
    const delivery = page.getByTestId('reports-delivery-month')
    await expect(delivery.first().getByRole('link', { name: 'Oct 2026' })).toHaveAttribute('aria-current', 'true')
    await expect(page.getByTestId('reports-trends').getByRole('listitem')).toHaveCount(4)
    // October holds the mock's runs, every kind with its row, and the two tickets it landed on its first day, the
    // latest first (canopy/serve/mock/history.py).
    await expect(page.getByTestId('reports-kinds')).toContainText('October 2026')
    await expect(page.getByTestId('reports-kind')).toHaveCount(6)
    // The mock's loop never read the runtime's sessions: none outside canopy.
    await expect(page.getByTestId('reports-outside')).toContainText('outside canopy')
    // Its four models, then the runs no session named one for: those canopy has yet to read, then those read to none.
    const models = page.getByTestId('reports-model').getByRole('rowheader')
    await expect(models).toHaveCount(6)
    await expect(models.nth(4)).toHaveText('unread')
    await expect(models.last()).toHaveText('none: no session named one')
    const landed = page.getByTestId('reports-landed-ticket')
    await expect(landed).toHaveCount(2)
    await expect(landed.first()).toContainText('ABC-091')
    await expect(landed.first()).toContainText('2 (1)')
    await expect(landed.first().getByRole('link', { name: /^acme\/web#\d+$/u })).toBeVisible()
})

test('a month picked shows in detail, from the chart or Delivery, and a span draws its every month', async ({
    page,
}) => {
    await page.goto('reports')
    await settled(page)
    // A year picked draws the months before the workspace took canopy up, in April.
    await page.getByTestId('reports-span-12').click()
    await expect(page).toHaveURL(/\/reports\?months=12$/u)
    await expect(page.getByTestId('reports-months-span')).toHaveText('12 months')
    await expect(page.getByTestId('reports-month')).toHaveCount(12)
    await page.getByTestId('reports-delivery-month').filter({ hasText: 'Mar 2026' }).getByRole('link').click()
    await expect(page).toHaveURL(/\/reports\?months=12&month=2026-03$/u)
    await expect(page.getByTestId('reports-kinds')).toContainText('nothing ran in March 2026')
    await expect(page.getByTestId('reports-models')).toContainText('nothing ran in March 2026')
    await expect(page.getByTestId('reports-landed')).toContainText('no tickets landed in March 2026')
    // August's workers ran alone, on one model, and landed two tickets: its bar picks it.
    await page.getByTestId('reports-bar-2026-08').click()
    await expect(page).toHaveURL(/\/reports\?months=12&month=2026-08$/u)
    await expect(page.getByTestId('reports-bar-2026-08')).toHaveAttribute('data-marked', 'true')
    await expect(page.getByTestId('reports-kinds')).toContainText('August 2026')
    await expect(page.getByTestId('reports-kind').filter({ hasText: 'workers' })).toContainText('$4.23')
    await expect(page.getByTestId('reports-model')).toHaveCount(1)
    await expect(page.getByTestId('reports-landed-ticket')).toHaveCount(2)

    await page.getByTestId('reports-span-6').click()
    await expect(page).toHaveURL(/\/reports\?months=6&month=2026-08$/u)
    await expect(page.getByTestId('reports-month')).toHaveCount(6)
    // Pressing the span shown lets it go, and the page fits the journal again.
    await page.getByTestId('reports-span-6').click()
    await expect(page).toHaveURL(/\/reports\?month=2026-08$/u)
    await expect(page.getByTestId('reports-months-span')).toHaveText('since April 2026')
})

test('the spend page sits under Reports, its card opens it on 30 days, and its old address still opens it', async ({
    page,
}) => {
    await page.goto('reports')
    await settled(page)
    await page.getByTestId('reports-card-spend').click()
    await expect(page).toHaveURL(/\/reports\/spend\?days=30$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Spend')
    await expect(page.getByTestId('spend-window-30')).toHaveAttribute('data-state', 'on')
    const trail = page.getByRole('navigation', { name: 'Breadcrumb' })
    await expect(trail.getByRole('link', { name: 'Reports' })).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Spend' })).toHaveAttribute(
        'data-status',
        'active',
    )

    await page.goto('spend?days=30&model_kind=workers')
    await expect(page).toHaveURL(/\/reports\/spend\?days=30&model_kind=workers$/u)
    await expect(page.getByTestId('spend-window-30')).toHaveAttribute('data-state', 'on')
})
