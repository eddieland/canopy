import { expect, test } from '@playwright/test'

import { ROUTES, settled, storeTheme, THEMES } from './helpers.ts'

for (const theme of THEMES) {
    for (const route of ROUTES) {
        test(`${route} in ${theme}`, async ({ page }) => {
            await storeTheme(page, theme)
            await page.goto(route)
            await settled(page)
            await expect(page.locator('html')).toHaveClass(theme === 'dark' ? /\bdark\b/ : /^(?!.*\bdark\b)/)
            await expect(page).toHaveScreenshot(`${route}-${theme}.png`, { fullPage: true })
        })
    }
}
