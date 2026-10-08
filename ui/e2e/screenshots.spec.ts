import { expect, test } from '@playwright/test'

import { NOW, ROUTES, settled, signIn, storeTheme, THEMES } from './helpers.ts'

for (const theme of THEMES) {
    for (const route of ROUTES) {
        test(`${route} in ${theme}`, async ({ page }) => {
            await page.clock.setFixedTime(NOW)
            await storeTheme(page, theme)
            await signIn(page)
            await page.goto(route)
            await settled(page)
            await expect(page.locator('html')).toHaveClass(theme === 'dark' ? /\bdark\b/ : /^(?!.*\bdark\b)/)
            await expect(page).toHaveScreenshot(`${route.replace('/', '-')}-${theme}.png`, { fullPage: true })
        })
    }

    test(`sign-in in ${theme}`, async ({ page }) => {
        await storeTheme(page, theme)
        await page.goto('attention')
        await expect(page.getByRole('heading', { level: 1 })).toHaveText('Sign in')
        await page.evaluate(async () => {
            await document.fonts.ready
        })
        await expect(page).toHaveScreenshot(`sign-in-${theme}.png`, { fullPage: true })
    })
}

// A wide screen: the interface is a quarter larger from a 2560px window, and the inbox and a ticket use the width.
test.describe('on a wide screen', () => {
    test.use({ viewport: { width: 2560, height: 1440 } })

    test('the root size grows with the window', async ({ page }) => {
        await signIn(page)
        await page.goto('attention')
        await settled(page)
        expect(await page.evaluate(() => getComputedStyle(document.documentElement).fontSize)).toBe('20px')
    })

    for (const route of ['attention', 'tickets/ABC-102'] as const) {
        test(`${route} wide`, async ({ page }) => {
            await page.clock.setFixedTime(NOW)
            await storeTheme(page, 'dark')
            await signIn(page)
            await page.goto(route)
            await settled(page)
            await expect(page).toHaveScreenshot(`${route.replace('/', '-')}-wide-dark.png`, { fullPage: true })
        })
    }
})
