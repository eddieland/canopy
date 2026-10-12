import { expect, type Page } from '@playwright/test'

import { E2E_SECRET } from './secret.ts'

export const STORAGE_KEY = 'canopy-theme'
// Every page, by its path; a screenshot each per theme.
export const ROUTES = [
    'attention',
    'runs',
    'runs/39',
    'worktrees',
    'tickets',
    'tickets/ABC-102',
    'chores',
    'chores/deps',
    'ticks',
    'ticks/2',
    'settings',
] as const
export const THEMES = ['light', 'dark'] as const
// Half an hour after the fixtures' T0 (canopy/serve/mock.py): every age on a page is the same on every run.
export const NOW = new Date('2026-10-08T12:30:00Z')

/** Stores `theme` before any page script runs, as if chosen on an earlier visit. */
export async function storeTheme(page: Page, theme: 'light' | 'dark'): Promise<void> {
    await page.addInitScript(
        ([key, value]) => {
            window.localStorage.setItem(key, value)
        },
        [STORAGE_KEY, theme] as const,
    )
}

/** Signs the page's browser in with the listener secret, as the sign-in page does: the cookie lands in its context. */
export async function signIn(page: Page): Promise<void> {
    const response = await page.request.post('api/session', { data: { secret: E2E_SECRET } })
    expect(response.status()).toBe(200)
}

/** Waits until the page is fully settled: fonts loaded, header counters filled, stream connected. */
export async function settled(page: Page): Promise<void> {
    await page.evaluate(async () => {
        await document.fonts.ready
    })
    const readouts = page.getByTestId('live-readouts')
    await expect(readouts.locator('[data-slot=skeleton]')).toHaveCount(0)
    await expect(page.getByTestId('stream-status')).toHaveAttribute('data-status', 'open')
    await expect(page.locator('main [data-slot=skeleton]')).toHaveCount(0)
}
