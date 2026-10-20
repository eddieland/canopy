import { expect, test } from '@playwright/test'

import { PALETTE_KEY, settled, signIn, STORAGE_KEY, storePalette, storeTheme } from './helpers.ts'

declare global {
    // A `var` in `declare global` is a property of globalThis, where the page's scripts set these.
    var canopyThemeProbe: { atBody?: string; atDomContentLoaded?: string; scheme?: string } | undefined
    var canopyViewTransitions: number | undefined
}

test.describe('no flash of the wrong theme', () => {
    test('a reload with dark stored has the class before the body, and at DOMContentLoaded', async ({ page }) => {
        await storeTheme(page, 'dark')
        // Records <html>'s class when <body> is first parsed (before any module script runs) and at DOMContentLoaded.
        await page.addInitScript(() => {
            const seen: NonNullable<typeof globalThis.canopyThemeProbe> = {}
            globalThis.canopyThemeProbe = seen
            new MutationObserver((_, observer) => {
                if (document.querySelector('body') !== null) {
                    seen.atBody = document.documentElement.className
                    observer.disconnect()
                }
            }).observe(document, { childList: true, subtree: true })
            document.addEventListener('DOMContentLoaded', () => {
                seen.atDomContentLoaded = document.documentElement.className
                seen.scheme = document.documentElement.style.colorScheme
            })
        })
        await page.goto('runs')
        await page.reload()
        const seen = await page.evaluate(() => globalThis.canopyThemeProbe)
        expect(seen?.atBody).toMatch(/\bdark\b/u)
        expect(seen?.atDomContentLoaded).toMatch(/\bdark\b/u)
        expect(seen?.scheme).toBe('dark')
    })

    test('with nothing stored it follows the system theme', async ({ page }) => {
        await page.emulateMedia({ colorScheme: 'dark' })
        await page.goto('runs')
        await expect(page.locator('html')).toHaveClass(/\bdark\b/u)
        await page.emulateMedia({ colorScheme: 'light' })
        await expect(page.locator('html')).not.toHaveClass(/\bdark\b/u)
    })
})

test.describe('the toggle', () => {
    test.beforeEach(async ({ page }) => {
        await signIn(page)
        // Counts view transitions, to tell the animated switch from the instant one.
        await page.addInitScript(() => {
            globalThis.canopyViewTransitions = 0
            const original = document.startViewTransition.bind(document)
            document.startViewTransition = ((...args: Parameters<typeof original>) => {
                globalThis.canopyViewTransitions = (globalThis.canopyViewTransitions ?? 0) + 1
                return original(...args)
            }) as typeof document.startViewTransition
        })
    })

    test('switches with a view transition, persists, and survives a reload', async ({ page }) => {
        await storeTheme(page, 'light')
        await page.goto('runs')
        await settled(page)
        const toggle = page.getByTestId('theme-toggle')
        await expect(toggle).toHaveAccessibleName('Switch to dark theme')

        await toggle.click()

        await expect(page.locator('html')).toHaveClass(/\bdark\b/u)
        await expect(toggle).toHaveAccessibleName('Switch to light theme')
        expect(await page.evaluate(() => globalThis.canopyViewTransitions)).toBe(1)
        expect(await page.evaluate((key) => localStorage.getItem(key), STORAGE_KEY)).toBe('dark')
        // Mid-reveal, for the record: the new theme grows from the button.
        await page.screenshot({ path: test.info().outputPath('toggle-done.png') })
    })

    test('swaps instantly when reduced motion is preferred', async ({ page }) => {
        await page.emulateMedia({ reducedMotion: 'reduce' })
        await storeTheme(page, 'light')
        await page.goto('runs')
        await settled(page)
        await page.getByTestId('theme-toggle').click()
        await expect(page.locator('html')).toHaveClass(/\bdark\b/u)
        expect(await page.evaluate(() => globalThis.canopyViewTransitions)).toBe(0)
    })

    test('the settings page picks a theme from the keyboard', async ({ page }) => {
        await storeTheme(page, 'light')
        await page.goto('settings')
        await settled(page)
        const themes = page.getByRole('radiogroup', { name: 'Theme' })
        // The arrows move between the themes, Space picks one, and Tab leaves for the next group's pick.
        await page.getByTestId('theme-light').focus()
        await page.keyboard.press('ArrowRight')
        await expect(themes.getByRole('radio', { name: 'Dark' })).toBeFocused()
        await page.keyboard.press('Space')
        await expect(page.locator('html')).toHaveClass(/\bdark\b/u)
        await expect(themes.getByRole('radio', { name: 'Dark' })).toHaveAttribute('aria-checked', 'true')
        await page.keyboard.press('Tab')
        await expect(page.getByTestId('palette-light-lavender')).toBeFocused()
    })

    test('a change in one tab reaches the others', async ({ context }) => {
        const first = await context.newPage()
        const second = await context.newPage()
        await signIn(first)
        await first.goto('settings')
        await second.goto('runs')
        await settled(second)

        await first.getByTestId('theme-dark').click()
        await expect(second.locator('html')).toHaveClass(/\bdark\b/u)

        await first.getByTestId('theme-system').click()
        await expect(second.locator('html')).toHaveAttribute('data-theme', 'system')
    })
})

test.describe('palettes', () => {
    test.beforeEach(async ({ page }) => {
        await signIn(page)
    })

    test("the settings page picks the dark theme's palette, and the canvas follows", async ({ page }) => {
        await storeTheme(page, 'dark')
        await page.goto('settings')
        await settled(page)
        const canvas = () =>
            page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--background'))
        const before = await canvas()

        await page.getByTestId('palette-dark-grey').click()

        await expect(page.locator('html')).toHaveAttribute('data-dark-palette', 'grey')
        await expect(
            page.getByRole('radiogroup', { name: 'Dark palette' }).getByRole('radio', { name: 'Grey' }),
        ).toHaveAttribute('aria-checked', 'true')
        await expect.poll(canvas).not.toBe(before)
        expect(await page.evaluate((key) => localStorage.getItem(key), PALETTE_KEY)).toBe(
            '{"light":"lavender","dark":"grey"}',
        )
    })

    test('a reload with a palette stored has it before the body', async ({ page }) => {
        await storeTheme(page, 'light')
        await storePalette(page, 'light', 'solarized')
        await page.addInitScript(() => {
            new MutationObserver((_, observer) => {
                if (document.querySelector('body') !== null) {
                    document.documentElement.dataset.paletteAtBody = document.documentElement.dataset.lightPalette
                    observer.disconnect()
                }
            }).observe(document, { childList: true, subtree: true })
        })
        await page.goto('runs')
        await expect(page.locator('html')).toHaveAttribute('data-palette-at-body', 'solarized')
    })

    test('a pick in one tab reaches the others, on any page', async ({ context }) => {
        const first = await context.newPage()
        const second = await context.newPage()
        await signIn(first)
        await first.goto('settings')
        await second.goto('runs')
        await settled(second)

        await first.getByTestId('palette-light-off-white').click()

        await expect(second.locator('html')).toHaveAttribute('data-light-palette', 'off-white')
    })
})
