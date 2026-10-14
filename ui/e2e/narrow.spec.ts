import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { NOW, ROUTES, settled, signIn } from './helpers.ts'

// Half of a second monitor, where the UI often sits: the rail a strip of icons.
const HALF = { width: 820, height: 900 }

test.beforeEach(async ({ page }) => {
    await page.clock.setFixedTime(NOW)
    await signIn(page)
})

test.describe('on half a monitor', () => {
    test.use({ viewport: HALF })

    for (const route of ROUTES) {
        test(`${route} fits the window's width`, async ({ page }) => {
            await page.goto(route)
            await settled(page)
            expect(await sideways(page)).toEqual({ window: 0, page: 0 })
        })
    }

    test("the tickets list keeps each ticket's title, its run, and its age, and lets its phase go", async ({
        page,
    }) => {
        await page.goto('tickets')
        await settled(page)
        const row = page.getByTestId('ticket-ABC-102')
        const title = await row.getByText('Export reports as CSV').boundingBox()
        // The free column's floor: 8rem.
        expect(title?.width ?? 0).toBeGreaterThanOrEqual(128)
        await expect(row.getByText('waiting on you')).toBeInViewport({ ratio: 1 })
        await expect(row.getByText(/ ago$/u)).toBeInViewport({ ratio: 1 })
        await expect(row.getByText('needs human')).toBeHidden()
    })

    test('the rail is a strip of the nav, and its button opens the whole rail over the page', async ({ page }) => {
        await page.goto('tickets')
        await settled(page)
        const strip = page.getByTestId('rail-strip')
        await expect(strip.getByRole('link', { name: 'Runs' })).toBeVisible()
        await expect(strip.getByTestId('nav-attention-count')).toHaveText(/^5/u)
        await expect(page.getByTestId('rail-working')).toHaveCount(0)

        await strip.getByRole('button', { name: 'Open the rail' }).click()
        const sheet = page.getByRole('dialog', { name: 'Rail' })
        // The rail's first item is the search box, so the sheet opens in it.
        await expect(sheet.getByRole('searchbox', { name: 'Search the journal' })).toBeFocused()
        await expect(sheet.getByTestId('rail-working').getByRole('link')).toHaveCount(3)
        await expect(sheet.getByTestId('rail-spend-24h')).toBeVisible()

        // A link followed leaves the page the sheet covered: it closes.
        await sheet.getByTestId('rail-run-41').click()
        await expect(page).toHaveURL(/\/runs\/41$/u)
        await expect(sheet).toHaveCount(0)
    })

    test('/ opens the rail in its search box, and a search sent closes it', async ({ page }) => {
        await page.goto('attention')
        await settled(page)
        await page.keyboard.press('/')
        const search = page.getByRole('dialog', { name: 'Rail' }).getByRole('searchbox', { name: 'Search the journal' })
        await expect(search).toBeFocused()
        await search.fill('web')
        await search.press('Enter')
        await expect(page).toHaveURL(/\/search\?q=web$/u)
        await expect(page.getByRole('dialog', { name: 'Rail' })).toHaveCount(0)
    })
})

/** How far the window and the page scroll sideways: neither should. */
function sideways(page: Page): Promise<{ window: number; page: number }> {
    return page.evaluate(() => {
        const root = document.documentElement
        const scroller = document.querySelector('[data-scroll-restoration-id=page]')
        return {
            window: root.scrollWidth - root.clientWidth,
            page: scroller === null ? 0 : scroller.scrollWidth - scroller.clientWidth,
        }
    })
}
