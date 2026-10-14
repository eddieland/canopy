import { expect, test } from '@playwright/test'

import { NOW, padDecisions, settled, signIn, storeTheme, THEMES } from './helpers.ts'

// Playwright starts headless Chromium with --hide-scrollbars, so no other screenshot shows one. This file keeps them:
// a long list scrolls inside its panel (PanelScroll), and its thin scrollbar is part of how it looks. The mock's lists
// are short, so the ticket's decisions are padded past the panel's height.
test.use({
    launchOptions: {
        executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined,
        ignoreDefaultArgs: ['--hide-scrollbars'],
    },
})

for (const theme of THEMES) {
    test(`a long list in ${theme}`, async ({ page }) => {
        await page.clock.setFixedTime(NOW)
        await storeTheme(page, theme)
        await signIn(page)
        await padDecisions(page, 'ABC-102', 12)
        await page.goto('tickets/ABC-102')
        await settled(page)
        await expect(page.locator('html')).toHaveClass(theme === 'dark' ? /\bdark\b/u : /^(?!.*\bdark\b)/u)
        await expect(page.getByTestId('ticket-decisions')).toHaveScreenshot(`long-list-${theme}.png`)
    })
}
