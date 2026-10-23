import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

// Opens a ticket's page, or its plan's (`path`), and waits until the browser keeps it as viewed: once its title loads.
async function view(page: Page, key: string, path = `tickets/${key}`): Promise<void> {
    await page.goto(path)
    await settled(page)
    await expect.poll(() => page.evaluate(() => localStorage.getItem('canopy-recent-tickets'))).toContain(`"${key}"`)
}

test('Ctrl+K Enter goes back to the ticket viewed before, and again comes back', async ({ page }) => {
    await view(page, 'ABC-099')
    await view(page, 'ABC-102')

    await page.keyboard.press('Control+k')
    const palette = page.getByRole('dialog', { name: 'Jump to a ticket' })
    await expect(palette).toBeVisible()
    // The ticket on screen is not offered: the first is the one before it.
    await expect(palette.getByRole('option')).toHaveCount(1)
    await expect(palette.getByRole('option').first()).toContainText('ABC-099')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/tickets\/ABC-099$/u)
    await expect(palette).toBeHidden()

    await page.keyboard.press('Control+k')
    await expect(palette.getByRole('option').first()).toContainText('ABC-102')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/tickets\/ABC-102$/u)
})

test('typing finds a ticket not viewed yet, and Escape closes the palette', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    // The keycap in the rail's search box opens it, as the keys do.
    await page.getByRole('button', { name: 'Jump to a ticket' }).click()
    const palette = page.getByRole('dialog', { name: 'Jump to a ticket' })
    await expect(palette.getByText('Tickets you open show up here. Type to find any ticket.')).toBeVisible()

    await palette.getByRole('combobox').fill('abc-105')
    await expect(palette.getByRole('group', { name: 'Tickets' }).getByRole('option')).toHaveCount(1)
    await page.keyboard.press('Escape')
    await expect(palette).toBeHidden()
    await expect(page).toHaveURL(/\/attention$/u)
})

test('the plan page counts as viewing its ticket, and the keys work from a text field', async ({ page }) => {
    await view(page, 'ABC-105', 'tickets/ABC-105/plan')
    await view(page, 'ABC-102')
    await page.getByRole('textbox').first().focus()

    await page.keyboard.press('Control+k')
    await expect(page.getByRole('dialog', { name: 'Jump to a ticket' }).getByRole('option').first()).toContainText(
        'ABC-105',
    )
})
