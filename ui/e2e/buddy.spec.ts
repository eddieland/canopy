import { expect, test } from '@playwright/test'

import { NOW, settled, signIn, storeTheme, THEMES } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('Sprig is off until Settings turns it on', async ({ page }) => {
    await page.goto('settings')
    await settled(page)
    await expect(page.getByTestId('buddy')).toHaveCount(0)
    await expect(page.getByTestId('buddy-off')).toHaveAttribute('aria-checked', 'true')

    await page.getByTestId('buddy-on').click()
    await expect(page.getByTestId('buddy-tip')).toBeVisible()
    await page.reload()
    await settled(page)
    await expect(page.getByTestId('buddy')).toBeVisible()
})

test.describe('turned on', () => {
    // As if turned on in Settings on an earlier visit; a choice made since, in the page, stands.
    test.beforeEach(async ({ page }) => {
        await page.addInitScript(() => {
            if (window.localStorage.getItem('canopy-buddy') === null) window.localStorage.setItem('canopy-buddy', 'on')
        })
    })

    test('Sprig offers a tip on every page, another on a click, and closes when told', async ({ page }) => {
        await page.goto('attention')
        await settled(page)
        const tip = page.getByTestId('buddy-tip')
        await expect(tip).toBeVisible()
        const first = await tip.textContent()

        await page.getByTestId('buddy-another').click()
        await expect(tip).not.toHaveText(first ?? '')
        const second = await tip.textContent()
        await page.getByTestId('buddy-sprig').click()
        await expect(tip).not.toHaveText(second ?? '')

        await page.getByTestId('buddy-close').click()
        await expect(tip).toHaveCount(0)
        await expect(page.getByTestId('buddy-sprig')).toBeVisible()

        // A new page, a new tip.
        await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Settings' }).click()
        await expect(page.getByRole('heading', { level: 1 })).toHaveText('Settings')
        await expect(tip).toBeVisible()
    })

    test("Don't show me tips again turns Sprig off until Settings turns it back on", async ({ page }) => {
        await page.goto('settings')
        await settled(page)
        const buddy = page.getByTestId('buddy')
        await expect(page.getByTestId('buddy-on')).toHaveAttribute('aria-checked', 'true')

        await page.getByTestId('buddy-dismiss').click()
        await expect(buddy).toHaveCount(0)
        await expect(page.getByTestId('buddy-off')).toHaveAttribute('aria-checked', 'true')
        await page.reload()
        await settled(page)
        await expect(buddy).toHaveCount(0)

        await page.getByTestId('buddy-on').click()
        await expect(buddy).toBeVisible()
        await expect(page.getByTestId('buddy-tip')).toBeVisible()
    })

    test("Sprig's eyes follow the pointer", async ({ page }) => {
        await page.goto('attention')
        await settled(page)
        const pupil = page.locator('[data-pupil]').first()
        await page.mouse.move(0, 0)
        await expect(pupil).toHaveAttribute('transform', /^translate\(-[\d.]+ -[\d.]+\)$/)
    })

    for (const theme of THEMES) {
        test(`Sprig in ${theme}`, async ({ page }) => {
            await page.clock.setFixedTime(NOW)
            await storeTheme(page, theme)
            await page.goto('attention')
            await settled(page)
            await expect(page.getByTestId('buddy')).toHaveScreenshot(`buddy-${theme}.png`)
        })
    }
})
