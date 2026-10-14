import { expect, test } from '@playwright/test'

import {
    LIGHT_ROUTES,
    NOW,
    ROUTES,
    screenshotMain,
    screenshotWhole,
    settled,
    signIn,
    storeTheme,
    THEMES,
    WHOLE_ROUTES,
} from './helpers.ts'

for (const theme of THEMES) {
    for (const route of ROUTES.filter((r) => theme === 'dark' || LIGHT_ROUTES.includes(r))) {
        test(`${route} in ${theme}`, async ({ page }) => {
            await page.clock.setFixedTime(NOW)
            await storeTheme(page, theme)
            await signIn(page)
            await page.goto(route)
            await settled(page)
            await expect(page.locator('html')).toHaveClass(theme === 'dark' ? /\bdark\b/u : /^(?!.*\bdark\b)/u)
            const screenshot = WHOLE_ROUTES.includes(route) ? screenshotWhole : screenshotMain
            await screenshot(page, `${route.replaceAll(/[/?=]/gu, '-')}-${theme}.png`)
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

    test(`a tick's output pretty in ${theme}`, async ({ page }) => {
        await page.clock.setFixedTime(NOW)
        await storeTheme(page, theme)
        await signIn(page)
        await page.goto('ticks/2')
        await settled(page)
        const output = page.getByTestId('tick-output')
        await output.getByRole('button', { name: 'Show' }).click()
        await output.getByRole('button', { name: 'Pretty' }).click()
        await expect(output.getByRole('button', { name: 'Pretty' })).toHaveAttribute('aria-pressed', 'true')
        await expect(output).toHaveScreenshot(`ticks-2-output-pretty-${theme}.png`)
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

// A tick's output as plain text: no color of its own, so dark alone.
test("a tick's output shown in dark", async ({ page }) => {
    await page.clock.setFixedTime(NOW)
    await storeTheme(page, 'dark')
    await signIn(page)
    await page.goto('ticks/2')
    await settled(page)
    const output = page.getByTestId('tick-output')
    await output.getByRole('button', { name: 'Show' }).click()
    await expect(output.getByTestId('tick-output-text')).toBeVisible()
    await expect(output).toHaveScreenshot('ticks-2-output-dark.png')
})

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

// Half of a second monitor: the rail a strip of the nav, each list showing the columns its width has room for.
test.describe('at half a monitor', () => {
    test.use({ viewport: { width: 820, height: 900 } })

    for (const route of ['attention', 'tickets', 'runs', 'tickets/ABC-102'] as const) {
        test(`${route} at half width`, async ({ page }) => {
            await page.clock.setFixedTime(NOW)
            await storeTheme(page, 'dark')
            await signIn(page)
            await page.goto(route)
            await settled(page)
            await screenshotWhole(page, `${route.replace('/', '-')}-half-dark.png`)
        })
    }
})
