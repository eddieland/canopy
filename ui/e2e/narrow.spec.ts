import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { expectSpendAxisWhole, FULL_RAIL, NOW, ROUTES, settled, signIn, windowWidth } from './helpers.ts'

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
        await expect(strip.getByTestId('nav-attention-count')).toHaveText(/^6/u)
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

    test('/spend?days=30 names its days whole, centered under their bars', async ({ page }) => {
        await page.goto('spend?days=30')
        await settled(page)
        await expectSpendAxisWhole(page, 6)
    })

    test("/spend?days=30 keeps the dearest day's total inside the chart when today is the dearest", async ({
        page,
    }) => {
        await page.goto('spend?days=30')
        await settled(page)
        // The mock prices today alone, the last of 30 bars, each narrower than the total over it. Centered, a total of
        // $1,234.56 would overhang the bar by more than the chart's padding, so on the last bar it is flush with the
        // bar's outer edge, whatever its length.
        const bar = page.getByTestId('spend-bar-2026-10-08')
        const [chart, barBox, label] = await Promise.all([
            page.getByTestId('spend-chart').boundingBox(),
            bar.boundingBox(),
            // The total's own box: the row holding it is only as wide as the bar.
            bar.getByTestId('spend-peak').locator('span').boundingBox(),
        ])
        if (chart === null || barBox === null || label === null) {
            throw new Error("the dearest day's total is not drawn")
        }
        expect(label.width).toBeGreaterThan(barBox.width)
        expect(Math.abs(label.x + label.width - (barBox.x + barBox.width))).toBeLessThanOrEqual(1)
        expect(label.x).toBeGreaterThanOrEqual(chart.x - 1)
        expect(label.x + label.width).toBeLessThanOrEqual(chart.x + chart.width + 1)
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

for (const width of [HALF.width, 1024]) {
    test.describe(`${width}px wide`, () => {
        test.use({ viewport: { width, height: 900 } })

        for (const days of [7, 30]) {
            test(`the By day table keeps 0.75rem between its columns over ${days} days`, async ({ page }) => {
                await page.goto(`spend?days=${days}`)
                await settled(page)
                const gaps = await page.getByTestId('spend-table').evaluate((table) =>
                    [...table.querySelectorAll('tr')].flatMap((row) => {
                        const cells = [...row.children].map((cell) => {
                            // The text's own box, not the cell's: a right-aligned figure sits at its cell's far edge.
                            const range = document.createRange()
                            range.selectNodeContents(cell)
                            return range.getBoundingClientRect()
                        })
                        return cells.slice(1).map((cell, i) => cell.left - (cells[i]?.right ?? 0))
                    }),
                )
                expect(gaps.length).toBeGreaterThan(0)
                // 0.75rem, less a pixel for where the text lands.
                expect(Math.min(...gaps)).toBeGreaterThanOrEqual(11)
            })
        }
    })
}

test("the worktrees counters stand four across or two by two, by the pane's width, never three and one", async ({
    page,
}) => {
    await page.goto('worktrees')
    await settled(page)
    const counters = page.getByTestId('pool-counters').locator(':scope > *')
    await expect(counters).toHaveCount(4)
    for (const [width, across] of [
        [820, 2],
        [960, 4],
        [FULL_RAIL, 4],
        [1440, 4],
    ] as const) {
        await windowWidth(page, width)
        const boxes = await counters.evaluateAll((els) =>
            els.map((el) => ({ left: el.getBoundingClientRect().left, top: el.getBoundingClientRect().top })),
        )
        // A grid's counters share their row's top and their column's left exactly: as many of each as it has.
        expect(new Set(boxes.map((box) => Math.round(box.left))).size, `columns at ${width}px`).toBe(across)
        expect(new Set(boxes.map((box) => Math.round(box.top))).size, `rows at ${width}px`).toBe(4 / across)
    }
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
