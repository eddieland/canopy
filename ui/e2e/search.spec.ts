import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('typing in the box opens the search, its hits grouped by source and linked to their pages', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const box = page.getByRole('searchbox', { name: 'Search the journal' })
    await box.fill('stale requests')

    await expect(page).toHaveURL(/\/search\?q=stale(\+|%20)requests$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('“stale requests”')
    const messages = page.getByTestId('search-message')
    await expect(messages.getByTestId('search-hit')).toHaveCount(1)
    await expect(messages.locator('mark')).toHaveText(['stale', 'requests'])
    await expect(messages.getByRole('link', { name: 'run:39' })).toBeVisible()

    await messages.getByRole('link', { name: 'ABC-099' }).click()
    await expect(page).toHaveURL(/\/tickets\/ABC-099$/)
    // Typing replaced the search's own history entries, so Back returns to the search, and the box keeps its query.
    await page.goBack()
    await expect(page).toHaveURL(/\/search\?q=/)
    await expect(box).toHaveValue('stale requests')
    await page.goBack()
    await expect(page).toHaveURL(/\/attention$/)
})

test('every source that holds a word has its panel, in the server order', async ({ page }) => {
    await page.goto('search?q=web')
    await expect(page.getByTestId('search-results').locator('> section')).toHaveCount(4)
    const order = await page
        .getByTestId('search-results')
        .locator('> section')
        .evaluateAll((panels) => panels.map((p) => p.dataset['testid']))
    expect(order).toEqual(['search-ticket', 'search-message', 'search-chore_run', 'search-decision'])
})

test('slash focuses the box from anywhere but a text field, and Escape leaves it', async ({ page }) => {
    await page.goto('ticks')
    await settled(page)
    const box = page.getByRole('searchbox', { name: 'Search the journal' })
    await page.keyboard.press('/')
    await expect(box).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(box).not.toBeFocused()

    await page.goto('tickets/ABC-102')
    await settled(page)
    const reply = page.getByRole('form', { name: 'Reply' }).locator('textarea')
    await reply.click()
    await page.keyboard.press('/')
    await expect(reply).toHaveValue('/')
    await expect(box).not.toBeFocused()
})

test('the clear button empties the box and keeps the focus there, leaving the page as it is', async ({ page }) => {
    await page.goto('search?q=web')
    await settled(page)
    const box = page.getByRole('searchbox', { name: 'Search the journal' })
    const clear = page.getByRole('button', { name: 'Clear search' })
    await expect(box).toHaveValue('web')

    await clear.click()
    await expect(box).toHaveValue('')
    await expect(box).toBeFocused()
    await expect(clear).toBeHidden()
    await expect(page).toHaveURL(/\/search\?q=web$/)

    await box.fill('stale requests')
    await expect(clear).toBeVisible()
    await expect(page).toHaveURL(/\/search\?q=stale(\+|%20)requests$/)
})

test('a query the server would refuse asks for one, and one nothing holds says so', async ({ page }) => {
    await page.goto('search?q=a')
    await expect(page.getByText('type at least 2 characters in the search box')).toBeVisible()
    await page.goto('search?q=zzzqqq')
    await expect(page.getByText('nothing in the journal holds every word')).toBeVisible()
})
