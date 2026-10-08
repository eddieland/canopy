import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('the root redirects to the attention list', async ({ page }) => {
    await page.goto('')
    await expect(page).toHaveURL(/\/attention$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Attention')
})

test('the nav moves between pages without reloading the shell', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.evaluate(() => {
        document.querySelector('[data-testid=app-header]')?.setAttribute('data-marker', 'kept')
    })
    const nav = page.getByRole('navigation', { name: 'Main' })

    await nav.getByRole('link', { name: 'Runs' }).click()
    await expect(page).toHaveURL(/\/runs$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Runs')
    await expect(nav.getByRole('link', { name: 'Runs' })).toHaveAttribute('data-status', 'active')

    await nav.getByRole('link', { name: 'Tickets' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Tickets')
    await page.getByTestId('tickets').getByRole('link', { name: 'ABC-102' }).click()
    await expect(page).toHaveURL(/\/tickets\/ABC-102$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('ABC-102')
    await expect(nav.getByRole('link', { name: 'Tickets' })).toHaveAttribute('data-status', 'active')

    await nav.getByRole('link', { name: 'Settings' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Settings')
    await expect(page.getByTestId('app-header')).toHaveAttribute('data-marker', 'kept')
})

test('search params are typed: a known state filters, an unknown one is dropped', async ({ page }) => {
    await page.goto('runs?state=blocked')
    const filters = page.getByRole('navigation', { name: 'Filter by state' })
    await expect(filters.getByRole('link', { name: 'blocked' })).toHaveAttribute('data-selected', 'true')
    await expect(filters.getByRole('link', { name: 'all' })).toHaveAttribute('data-selected', 'false')
    await expect(page.getByTestId('runs').locator('li')).toHaveCount(1)

    // The router leaves the URL as typed; what matters is the page never sees the value.
    await page.goto('runs?state=bogus')
    await expect(filters.getByRole('link', { name: 'all' })).toHaveAttribute('data-selected', 'true')
    await expect(page.getByTestId('runs').locator('li')).not.toHaveCount(1)
})

test('an unknown route renders the not-found page inside the shell', async ({ page }) => {
    await page.goto('nowhere')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Nothing here')
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
})

test('a ticket the journal does not know offers to start it', async ({ page }) => {
    await page.goto('tickets/ZZZ-9')
    await expect(page.getByText('canopy has no record of it')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start privately' })).toBeVisible()
})
