import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the rail's foot opens the guide at its first page, its pages listed by group beside it", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('rail-guide').click()
    await expect(page).toHaveURL(/\/guide\/overview$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('The web UI')
    await expect(page).toHaveTitle(/^(?:\(\d+\) )?The web UI · Guide · canopy$/u)
    const sidebar = page.getByRole('navigation', { name: 'Guide' })
    await expect(sidebar.getByRole('region', { name: 'Getting started' })).toBeVisible()
    await expect(sidebar.getByRole('link', { name: 'The web UI' })).toHaveAttribute('aria-current', 'page')
    await expect(sidebar.getByRole('link', { name: 'Signing in' })).not.toHaveAttribute('aria-current', 'page')
})

test('a page links to a heading on it, to the next page and back, and to a section of the app', async ({ page }) => {
    await page.goto('guide/overview')

    await page.getByRole('navigation', { name: 'On this page' }).getByRole('link', { name: 'The rail' }).click()
    await expect(page).toHaveURL(/\/guide\/overview#the-rail$/u)
    await expect(page.getByRole('heading', { level: 2, name: 'The rail' })).toBeInViewport()

    const steps = page.getByRole('navigation', { name: 'Previous and next' })
    await steps.getByRole('link', { name: /Next.*Signing in/u }).click()
    await expect(page).toHaveURL(/\/guide\/signing-in$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Signing in')
    await steps.getByRole('link', { name: /Previous.*The web UI/u }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('The web UI')

    await page.getByTestId('guide-page').getByRole('link', { name: 'Signing in', exact: true }).click()
    await page.getByTestId('guide-page').getByRole('link', { name: 'Settings' }).click()
    await expect(page).toHaveURL(/\/settings$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Settings')
})

test('under lg, the guide pages fold into a toggle above the page', async ({ page }) => {
    await page.setViewportSize({ width: 800, height: 900 })
    await page.goto('guide/overview')
    await expect(page.getByRole('navigation', { name: 'Guide' })).toBeHidden()
    await page.getByRole('button', { name: 'Guide pages' }).click()
    await page.getByRole('navigation', { name: 'Guide' }).getByRole('link', { name: 'Signing in' }).click()
    await expect(page).toHaveURL(/\/guide\/signing-in$/u)
})

test('a page the guide does not have is the 404', async ({ page }) => {
    await page.goto('guide/no-such-page')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Nothing here')
})
