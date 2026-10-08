import { expect, type Page } from '@playwright/test'

export const STORAGE_KEY = 'canopy-theme'
export const ROUTES = ['sessions', 'worktrees', 'settings'] as const
export const THEMES = ['light', 'dark'] as const

/** Stores `theme` before any page script runs, as if chosen on an earlier visit. */
export async function storeTheme(page: Page, theme: 'light' | 'dark'): Promise<void> {
    await page.addInitScript(
        ([key, value]) => {
            window.localStorage.setItem(key, value)
        },
        [STORAGE_KEY, theme] as const,
    )
}

/** Waits until the page is fully settled: fonts loaded, header counters filled, stream connected. */
export async function settled(page: Page): Promise<void> {
    await page.evaluate(async () => {
        await document.fonts.ready
    })
    const readouts = page.getByTestId('live-readouts')
    await expect(readouts.locator('[data-slot=skeleton]')).toHaveCount(0)
    await expect(page.getByTestId('stream-status')).toHaveAttribute('data-status', 'open')
}
