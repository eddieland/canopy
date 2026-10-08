import { expect, test } from '@playwright/test'

import { settled } from './helpers.ts'

test('the root redirects to sessions', async ({ page }) => {
    await page.goto('')
    await expect(page).toHaveURL(/\/sessions$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Sessions')
})

test('the nav moves between pages without reloading the shell', async ({ page }) => {
    await page.goto('sessions')
    await settled(page)
    await page.evaluate(() => {
        document.querySelector('[data-testid=app-header]')?.setAttribute('data-marker', 'kept')
    })
    const nav = page.getByRole('navigation', { name: 'Main' })

    await nav.getByRole('link', { name: 'Worktrees' }).click()
    await expect(page).toHaveURL(/\/worktrees$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Worktrees')
    await expect(nav.getByRole('link', { name: 'Worktrees' })).toHaveAttribute('data-status', 'active')

    await nav.getByRole('link', { name: 'Settings' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Settings')
    await expect(page.getByTestId('app-header')).toHaveAttribute('data-marker', 'kept')
})

test('search params are typed: a known state filters, an unknown one is dropped', async ({ page }) => {
    await page.goto('sessions?state=blocked')
    const filters = page.getByRole('navigation', { name: 'Filter by state' })
    await expect(filters.getByRole('link', { name: 'blocked' })).toHaveAttribute('data-selected', 'true')
    await expect(filters.getByRole('link', { name: 'all' })).toHaveAttribute('data-selected', 'false')
    await expect(page.getByText('filtered to blocked')).toBeVisible()

    // The router leaves the URL as typed; what matters is the page never sees the value.
    await page.goto('sessions?state=bogus')
    await expect(filters.getByRole('link', { name: 'all' })).toHaveAttribute('data-selected', 'true')
    await expect(page.getByText('filtered to')).toHaveCount(0)
})

test('an unknown route renders the not-found page inside the shell', async ({ page }) => {
    await page.goto('nowhere')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Nothing here')
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
})
