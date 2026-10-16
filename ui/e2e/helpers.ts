import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'

import { E2E_SECRET } from './secret.ts'

/** Where the page keeps the theme preference: the same key as src/theme/store.ts. */
export const STORAGE_KEY = 'canopy-theme'
/** Every page, by its path and any query; a screenshot each in dark, of its main pane alone unless in WHOLE_ROUTES. */
export const ROUTES = [
    'attention',
    'runs',
    'runs/39',
    'runs/41',
    'worktrees',
    'tickets',
    'tickets/ABC-102',
    'pull-requests',
    `pull-requests/pr?url=${encodeURIComponent('https://github.com/acme/web/pull/88')}`,
    'reviews',
    'reviews/4',
    'chores',
    'chores/deps',
    'chores/deps/runs/2',
    'ticks',
    'ticks/2',
    'spend',
    'settings',
    'search?q=web',
    'plan-editor',
] as const
/** A page in ROUTES. */
export type Route = (typeof ROUTES)[number]
/**
 * The pages screenshotted whole, the shell included: the ones README.md shows. The rest show their main pane alone, so
 * a change to the header or the rail rewrites these images and not every one.
 */
export const WHOLE_ROUTES: readonly Route[] = ['attention', 'tickets/ABC-102', 'runs/39', 'reviews/4', 'ticks/2']
/**
 * The pages screenshotted in light as well: the shell, a list, and a detail page. Both themes draw from the same
 * tokens, so a few pages in light catch a light token gone wrong without doubling every image.
 */
export const LIGHT_ROUTES: readonly Route[] = ['attention', 'runs', 'tickets/ABC-102']
/** The themes the app has; a page is screenshotted in light only if in LIGHT_ROUTES. */
export const THEMES = ['light', 'dark'] as const
/** Half an hour after the fixtures' T0 (canopy/serve/mock.py): every age on a page is the same on every run. */
export const NOW = new Date('2026-10-08T12:30:00Z')

/** Stores `theme` before any page script runs, as if chosen on an earlier visit. */
export async function storeTheme(page: Page, theme: 'light' | 'dark'): Promise<void> {
    await page.addInitScript(
        ([key, value]) => {
            globalThis.localStorage.setItem(key, value)
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

/** Screenshots the whole page as `name`, the header and the rail included. */
export async function screenshotWhole(page: Page, name: string): Promise<void> {
    await growToPage(page)
    await expect(page).toHaveScreenshot(name)
}

/** Screenshots the page's main pane as `name`, without the header and the rail around it. */
export async function screenshotMain(page: Page, name: string): Promise<void> {
    await growToPage(page)
    await expect(page.locator('main')).toHaveScreenshot(name)
}

/**
 * Grows the window to the page's height. The page scrolls under the header, not the window (AppShell), so a capture
 * would stop at the window's foot.
 */
async function growToPage(page: Page): Promise<void> {
    const scroller = page.locator('[data-scroll-restoration-id=page]')
    const height = await scroller.evaluate((el) => el.getBoundingClientRect().top + el.scrollHeight)
    const viewport = page.viewportSize()
    if (viewport === null) {
        throw new Error('the page has no viewport to grow')
    }
    await page.setViewportSize({ width: viewport.width, height: Math.max(viewport.height, Math.ceil(height)) })
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

/** Makes a ticket's conversation `count` messages long, its recorded ones over and over, so it scrolls. */
export async function padMessages(page: Page, ticketKey: string, count: number): Promise<void> {
    await page.route(`**/api/tickets/${ticketKey}`, async (route) => {
        const response = await route.fetch()
        const body = (await response.json()) as { messages: { id: number }[] }
        const recorded = body.messages
        body.messages = Array.from({ length: count }, (_, i) => ({ ...recorded[i % recorded.length], id: 1000 + i }))
        await route.fulfill({ response, json: body })
    })
}

/**
 * Makes canopy's lifetime spend `usd`, as `GET /api/spend` and the event stream report it, for the hat shop: the mock
 * has spent too little to buy a hat. The stream's messages are rewritten in the page, as each is read, since a stream
 * never ends for a route to read whole.
 */
export async function spentInAll(page: Page, usd: number): Promise<void> {
    await page.route('**/api/spend', async (route) => {
        const response = await route.fetch()
        const body = (await response.json()) as { total_usd: number | null }
        body.total_usd = usd
        await route.fulfill({ response, json: body })
    })
    await page.addInitScript((total) => {
        // The getter is only ever called with `.call` on an event, so it never loses its `this`.
        // oxlint-disable-next-line typescript/unbound-method
        const read = Object.getOwnPropertyDescriptor(MessageEvent.prototype, 'data')?.get
        Object.defineProperty(MessageEvent.prototype, 'data', {
            get(this: MessageEvent): unknown {
                const data: unknown = read?.call(this)
                if (!(this.target instanceof EventSource) || typeof data !== 'string') {
                    return data
                }
                const parsed = JSON.parse(data) as { type?: string; spend?: { total_usd: number | null } }
                if (parsed.type !== 'spend.updated' || parsed.spend === undefined) {
                    return data
                }
                parsed.spend.total_usd = total
                return JSON.stringify(parsed)
            },
        })
    }, usd)
}
