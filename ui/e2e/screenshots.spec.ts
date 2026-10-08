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
