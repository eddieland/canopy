import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { NOW, settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await page.clock.setFixedTime(NOW)
    await signIn(page)
})

/** The keys of the tickets the list shows, sorted: the order is the list's own, by activity. */
async function keys(page: Page): Promise<string[]> {
    const ids = await page
        .getByTestId('tickets')
        .locator('[data-testid^="ticket-"]')
        .evaluateAll((rows) => rows.map((r) => r.dataset.testid ?? ''))
    return ids.map((id) => id.replace(/^ticket-/u, '')).toSorted()
}

test('a filter by where a ticket stands keeps the tickets standing there, in the URL', async ({ page }) => {
    await page.goto('tickets')
    await settled(page)
    const filters = page.getByRole('navigation', { name: 'Filter by where it stands' })
    await expect(filters.getByRole('link', { name: 'all' })).toHaveAttribute('data-selected', 'true')

    await filters.getByRole('link', { name: 'working' }).click()
    await expect(page).toHaveURL(/\/tickets\?show=working$/u)
    await expect.poll(() => keys(page)).toEqual(['ABC-101', 'ABC-104'])
    await expect(page.getByTestId('tickets-count')).toHaveText(/^2 of \d+$/u)

    await filters.getByRole('link', { name: 'waiting on you' }).click()
    await expect.poll(() => keys(page)).toEqual(['ABC-102'])

    // Each ticket the months before the mock's day landed or closed (canopy/serve/mock/history.py).
    await filters.getByRole('link', { name: 'done' }).click()
    await expect(page.getByTestId('tickets-count')).toHaveText(/^21 of \d+$/u)

    await filters.getByRole('link', { name: 'all' }).click()
    await expect(page).toHaveURL(/\/tickets$/u)
})

test('the text filter keeps the tickets whose key or title holds every word, and Back leaves it', async ({ page }) => {
    await page.goto('runs')
    await page.goto('tickets?show=open')
    await settled(page)
    const field = page.getByRole('searchbox', { name: 'Filter tickets by key or title' })

    await field.fill('csv EXPORT')
    await expect(page).toHaveURL(/[?&]q=csv(\+|%20)EXPORT/u)
    await expect(page).toHaveURL(/[?&]show=open/u)
    await expect.poll(() => keys(page)).toEqual(['ABC-102'])

    await field.fill('104')
    await expect.poll(() => keys(page)).toEqual(['ABC-104'])

    await field.fill('nothing like it')
    await expect(page.getByText('no open tickets with “nothing like it” in the key or title')).toBeVisible()

    // Each keystroke replaced the entry: Back leaves the page, not the last word typed.
    await page.goBack()
    await expect(page).toHaveURL(/\/runs$/u)
})

test('a text filter in the URL fills the field and filters the list on load', async ({ page }) => {
    await page.goto('tickets?q=sso')
    await settled(page)
    await expect(page.getByRole('searchbox', { name: 'Filter tickets by key or title' })).toHaveValue('sso')
    await expect.poll(() => keys(page)).toEqual(['ABC-101'])
})

test('the board lays the tickets out by stage, in the URL, under the same filters', async ({ page }) => {
    await page.goto('tickets?show=open')
    await settled(page)
    await page.getByRole('radiogroup', { name: 'Lay out as' }).getByRole('radio', { name: 'board' }).click()
    await expect(page).toHaveURL(/[?&]view=board/u)
    await expect(page).toHaveURL(/[?&]show=open/u)

    const board = page.getByRole('region', { name: 'Tickets by stage' })
    // A ticket a run is on is working, whatever phase it was in; one with a red PR is in CI.
    await expect(board.getByRole('region', { name: /^working \d+$/u }).getByTestId('ticket-ABC-104')).toBeVisible()
    await expect(board.getByRole('region', { name: /^CI \d+$/u }).getByTestId('ticket-ABC-100')).toBeVisible()
    await expect(board.getByRole('region', { name: 'done 0' })).toBeVisible()

    await page.getByRole('searchbox', { name: 'Filter tickets by key or title' }).fill('csv')
    await expect(board.getByRole('listitem')).toHaveCount(1)
    await expect(board.getByTestId('ticket-ABC-102')).toBeVisible()

    await page.getByRole('radiogroup', { name: 'Lay out as' }).getByRole('radio', { name: 'list' }).click()
    await expect(page).not.toHaveURL(/view=/u)
    await expect(page.getByTestId('tickets').getByTestId('ticket-ABC-102')).toBeVisible()
})
