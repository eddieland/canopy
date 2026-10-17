import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the rail's foot opens the guide, which lists its pages", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('rail-guide').click()
    await expect(page).toHaveURL(/\/guide$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Guide')
    await expect(page).toHaveTitle(/^(?:\(\d+\) )?Guide · canopy$/u)
    const pages = page.getByTestId('guide-pages')
    await expect(pages.getByRole('link', { name: 'The web UI' })).toBeVisible()
    await expect(pages.getByRole('link', { name: 'Signing in' })).toBeVisible()
})

test('a page links to another page, to a heading on it, and to a section of the app', async ({ page }) => {
    await page.goto('guide')
    await page.getByTestId('guide-pages').getByRole('link', { name: 'The web UI' }).click()
    await expect(page).toHaveURL(/\/guide\/overview$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('The web UI')
    await expect(
        page.getByRole('navigation', { name: 'Guide' }).getByRole('link', { name: 'The web UI' }),
    ).toHaveAttribute('data-status', 'active')

    await page.getByRole('navigation', { name: 'On this page' }).getByRole('link', { name: 'The rail' }).click()
    await expect(page).toHaveURL(/\/guide\/overview#the-rail$/u)
    await expect(page.getByRole('heading', { level: 2, name: 'The rail' })).toBeInViewport()

    await page.getByTestId('guide-page').getByRole('link', { name: 'Signing in' }).click()
    await expect(page).toHaveURL(/\/guide\/signing-in$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Signing in')

    await page.getByTestId('guide-page').getByRole('link', { name: 'Settings' }).click()
    await expect(page).toHaveURL(/\/settings$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Settings')
})

test('a page the guide does not have is the 404', async ({ page }) => {
    await page.goto('guide/no-such-page')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Nothing here')
})
