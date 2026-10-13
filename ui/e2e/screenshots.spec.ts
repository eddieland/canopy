import { expect, test } from '@playwright/test'

import { NOW, ROUTES, screenshotWhole, settled, signIn, storeTheme, THEMES } from './helpers.ts'

for (const theme of THEMES) {
    for (const route of ROUTES) {
        test(`${route} in ${theme}`, async ({ page }) => {
            await page.clock.setFixedTime(NOW)
            await storeTheme(page, theme)
            await signIn(page)
            await page.goto(route)
            await settled(page)
            await expect(page.locator('html')).toHaveClass(theme === 'dark' ? /\bdark\b/ : /^(?!.*\bdark\b)/)
            await screenshotWhole(page, `${route.replace(/[/?=]/g, '-')}-${theme}.png`)
        })
    }

    // What a page shows only when opened: JSON colored in a tool call's input and output, and in a tick's output.
    test(`an opened tool call in ${theme}`, async ({ page }) => {
        await page.clock.setFixedTime(NOW)
        await storeTheme(page, theme)
        await signIn(page)
        await page.goto('runs/39')
        await settled(page)
        const call = page.getByTestId('transcript-tool').filter({ hasText: 'jira_get_issue' }).first()
        await call.locator('summary').click()
        await expect(call).toHaveScreenshot(`runs-39-tool-call-${theme}.png`)
    })

    test(`a tick's output shown in ${theme}`, async ({ page }) => {
        await page.clock.setFixedTime(NOW)
        await storeTheme(page, theme)
        await signIn(page)
        await page.goto('ticks/2')
        await settled(page)
        const output = page.getByTestId('tick-output')
        await output.getByRole('button', { name: 'Show' }).click()
        await expect(output.getByTestId('tick-output-text')).toBeVisible()
        await expect(output).toHaveScreenshot(`ticks-2-output-${theme}.png`)
    })

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
            await screenshotWhole(page, `${route.replace('/', '-')}-wide-dark.png`)
        })
    }
})
