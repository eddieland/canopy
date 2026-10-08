import { expect, test } from '@playwright/test'

import { settled, signIn, STORAGE_KEY, storeTheme } from './helpers.ts'

declare global {
    interface Window {
        canopyThemeProbe?: { atBody?: string; atDomContentLoaded?: string; scheme?: string }
        canopyViewTransitions?: number
    }
}

test.describe('no flash of the wrong theme', () => {
    test('a reload with dark stored has the class before the body, and at DOMContentLoaded', async ({ page }) => {
        await storeTheme(page, 'dark')
        // Records <html>'s class when <body> is first parsed (before any module script runs) and at DOMContentLoaded.
        await page.addInitScript(() => {
            const seen: NonNullable<Window['canopyThemeProbe']> = {}
            window.canopyThemeProbe = seen
            new MutationObserver((_, observer) => {
                if (document.body) {
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
        const seen = await page.evaluate(() => window.canopyThemeProbe)
        expect(seen?.atBody).toMatch(/\bdark\b/)
        expect(seen?.atDomContentLoaded).toMatch(/\bdark\b/)
        expect(seen?.scheme).toBe('dark')
    })

    test('with nothing stored it follows the system theme', async ({ page }) => {
        await page.emulateMedia({ colorScheme: 'dark' })
        await page.goto('runs')
        await expect(page.locator('html')).toHaveClass(/\bdark\b/)
        await page.emulateMedia({ colorScheme: 'light' })
        await expect(page.locator('html')).not.toHaveClass(/\bdark\b/)
    })
})

test.describe('the toggle', () => {
    test.beforeEach(async ({ page }) => {
        await signIn(page)
        // Counts view transitions, to tell the animated switch from the instant one.
        await page.addInitScript(() => {
            window.canopyViewTransitions = 0
            const original = document.startViewTransition?.bind(document)
            if (original) {
                document.startViewTransition = ((...args: Parameters<typeof original>) => {
                    window.canopyViewTransitions = (window.canopyViewTransitions ?? 0) + 1
                    return original(...args)
                }) as typeof document.startViewTransition
            }
        })
    })

    test('switches with a view transition, persists, and survives a reload', async ({ page }) => {
        await storeTheme(page, 'light')
        await page.goto('runs')
        await settled(page)
        const toggle = page.getByTestId('theme-toggle')
        await expect(toggle).toHaveAccessibleName('Switch to dark theme')

        await toggle.click()

        await expect(page.locator('html')).toHaveClass(/\bdark\b/)
        await expect(toggle).toHaveAccessibleName('Switch to light theme')
        expect(await page.evaluate(() => window.canopyViewTransitions)).toBe(1)
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
        await expect(page.locator('html')).toHaveClass(/\bdark\b/)
        expect(await page.evaluate(() => window.canopyViewTransitions)).toBe(0)
    })

    test('a change in one tab reaches the others', async ({ context }) => {
        const first = await context.newPage()
        const second = await context.newPage()
        await signIn(first)
        await first.goto('settings')
        await second.goto('runs')
        await settled(second)

        await first.getByTestId('theme-dark').click()
        await expect(second.locator('html')).toHaveClass(/\bdark\b/)

        await first.getByTestId('theme-system').click()
        await expect(second.locator('html')).toHaveAttribute('data-theme', 'system')
    })
})
