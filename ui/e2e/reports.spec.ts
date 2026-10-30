import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('the nav opens Reports, a year of months newest first with the latest in detail', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Reports' }).click()
    await expect(page).toHaveURL(/\/reports$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Reports')
    await expect(page.getByTestId('reports-span-12')).toHaveAttribute('data-state', 'on')
    const months = page.getByTestId('reports-month')
    await expect(months).toHaveCount(12)
    await expect(months.first().getByRole('rowheader')).toHaveText('Oct 2026')
    await expect(months.last().getByRole('rowheader')).toHaveText('Nov 2025')
    await expect(months.first().getByRole('link', { name: 'Oct 2026' })).toHaveAttribute('aria-current', 'true')
    // October holds the mock's runs, every kind with its row, and the two tickets it landed on its first day, the
    // latest first (canopy/serve/mock/history.py).
    await expect(page.getByTestId('reports-kinds')).toContainText('October 2026')
    await expect(page.getByTestId('reports-kind')).toHaveCount(6)
    // The mock's loop never read the runtime's sessions: none outside canopy.
    await expect(page.getByTestId('reports-outside')).toContainText('outside canopy')
    await expect(page.getByTestId('reports-model').first()).toBeVisible()
    const landed = page.getByTestId('reports-landed-ticket')
    await expect(landed).toHaveCount(2)
    await expect(landed.first()).toContainText('ABC-091')
    await expect(landed.first()).toContainText('2 (1)')
})

test('a month picked shows in detail, and the span narrows the months', async ({ page }) => {
    await page.goto('reports')
    await settled(page)
    // The mock's workspace took canopy up in April.
    await page.getByTestId('reports-month').filter({ hasText: 'Mar 2026' }).getByRole('link').click()
    await expect(page).toHaveURL(/\/reports\?month=2026-03$/u)
    await expect(page.getByTestId('reports-kinds')).toContainText('nothing ran in March 2026')
    await expect(page.getByTestId('reports-models')).toContainText('nothing ran in March 2026')
    await expect(page.getByTestId('reports-landed')).toContainText('no tickets landed in March 2026')
    // August's workers ran alone, on one model, and landed two tickets.
    await page.getByTestId('reports-month').filter({ hasText: 'Aug 2026' }).getByRole('link').click()
    await expect(page).toHaveURL(/\/reports\?month=2026-08$/u)
    await expect(page.getByTestId('reports-kinds')).toContainText('August 2026')
    await expect(page.getByTestId('reports-kind').filter({ hasText: 'workers' })).toContainText('$4.23')
    await expect(page.getByTestId('reports-model')).toHaveCount(1)
    await expect(page.getByTestId('reports-landed-ticket')).toHaveCount(2)

    await page.getByTestId('reports-span-6').click()
    await expect(page).toHaveURL(/\/reports\?month=2026-08&months=6$/u)
    await expect(page.getByTestId('reports-month')).toHaveCount(6)
    // The default span needs no search.
    await page.getByTestId('reports-span-12').click()
    await expect(page).toHaveURL(/\/reports\?month=2026-08$/u)
})

test('the spend page sits under Reports, and its old address still opens it', async ({ page }) => {
    await page.goto('reports')
    await settled(page)
    await page.getByTestId('reports-spend-link').click()
    await expect(page).toHaveURL(/\/reports\/spend$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Spend')
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
