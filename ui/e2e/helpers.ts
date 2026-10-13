import { expect, type Page } from '@playwright/test'

import { E2E_SECRET } from './secret.ts'

export const STORAGE_KEY = 'canopy-theme'
// Every page, by its path and any query; a screenshot each per theme.
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
    'search?q=web',
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

/**
 * Pads a ticket's decisions to `count`, cycling through the ones the mock records, as a long-lived ticket collects
 * them: the mock's are too few to fill a panel past its height.
 */
export async function padDecisions(page: Page, ticketKey: string, count: number): Promise<void> {
    await page.route(`**/api/tickets/${ticketKey}`, async (route) => {
        const response = await route.fetch()
        const body = (await response.json()) as { decisions: { id: number }[] }
        const recorded = body.decisions
        body.decisions = Array.from({ length: count }, (_, i) => ({ ...recorded[i % recorded.length], id: 1000 + i }))
        await route.fulfill({ response, json: body })
    })
}
