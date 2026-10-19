import { expect, test } from '@playwright/test'

import { expectSpendAxisWhole, settled, signIn } from './helpers.ts'

/** A spend breakdown's costs, by name. */
type Costs = Record<string, number | null>

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the rail's counters open the spend page, whose total agrees with the 30 days'", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const month = await page.getByTestId('rail-spend-30d').textContent()

    await page.getByTestId('rail-spend-link-24h').click()
    await expect(page).toHaveURL(/\/spend$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Spend')
    await expect(page.getByTestId('spend-window-7')).toHaveAttribute('data-state', 'on')
    await expect(page.getByTestId('spend-chart').getByTestId(/^spend-bar-/u)).toHaveCount(7)

    await page.goto('attention')
    await page.getByTestId('rail-spend-link-30d').click()
    await expect(page).toHaveURL(/\/spend\?days=30$/u)
    await expect(page.getByTestId('spend-window-30')).toHaveAttribute('data-state', 'on')
    await expect(page.getByTestId('spend-chart').getByTestId(/^spend-bar-/u)).toHaveCount(30)
    // Every run in the mock journal started within the 30 days, so the window's total is the rail's.
    await expect(page.getByTestId('spend-total-total')).toHaveText(month ?? '')
})

test('the window switches from the toggle, and idle spend is its own series with its ticks linked', async ({
    page,
}) => {
    await page.goto('spend?days=30')
    await settled(page)
    await page.getByTestId('spend-window-7').click()
    await expect(page).toHaveURL(/\/spend$/u)
    await expect(page.getByTestId('spend-table').locator('tbody tr')).toHaveCount(7)

    // The mock's second tick was idle: its overseer's cost is the idle series, and the share of the overseer's.
    await expect(page.getByTestId('spend-total-idle')).toHaveText('$0.31')
    await expect(page.getByTestId('spend-total-overseer')).toHaveText('$0.59')
    await expect(page.getByTestId('spend-idle-share')).toContainText('53%')
    await expect(page.getByTestId('spend-groups-idle')).toContainText('1')
    await expect(page.getByTestId('spend-woken-table-timer')).toBeVisible()
    const today = page.getByTestId('spend-day-2026-10-08')
    await expect(today.locator('td').first()).toHaveText('$0.31')

    const ticks = page.getByTestId('spend-idle-tick-list')
    await expect(ticks.getByTestId(/^tick-\d+$/u)).toHaveCount(1)
    await ticks.getByRole('link', { name: 'tick:2' }).click()
    await expect(page).toHaveURL(/\/ticks\/2$/u)
})

test("each series has one name in the totals, the legend, and the table, and the description is the window's", async ({
    page,
}) => {
    await page.goto('spend')
    await settled(page)
    // The window's state, with what the page holds on the title's hover.
    const total = await page.getByTestId('spend-total-total').textContent()
    await expect(page.locator('main header p')).toHaveText(`${total ?? ''} over 7 days · no tickets done`)
    await expect(page.getByRole('heading', { level: 1 })).toHaveAttribute('title', /canopy spend --days N/u)

    const series = ['idle ticks', 'overseer', 'workers', 'plan triage', 'plans', 'chores', 'reviews', 'dry runs']
    await expect(page.getByTestId('spend-legend').getByRole('listitem')).toHaveText(series)
    await expect(page.getByTestId('spend-table').locator('thead th')).toHaveText(['day', ...series, 'total', 'done'])
    // The totals name the overseer's whole before idle ticks' part of it, as canopy spend's columns do.
    const totals = page.getByTestId('spend-totals').locator('dt')
    await expect(totals).toHaveText([
        'total',
        'overseer',
        'idle ticks',
        'workers',
        'plan triage',
        'plans',
        'chores',
        'reviews',
        'dry runs',
        'tickets done',
        'per ticket done',
        'plans waived',
    ])
    await expect(page.getByText('other ticks')).toHaveCount(0)
})

test('a window the page does not offer reads as the week', async ({ page }) => {
    await page.goto('spend?days=9')
    await settled(page)
    await expect(page.getByTestId('spend-window-7')).toHaveAttribute('data-state', 'on')
    await expect(page.getByTestId('spend-table').locator('tbody tr')).toHaveCount(7)
})

test('the nav opens the spend page on the week, its item marked', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const nav = page.getByRole('navigation', { name: 'Main' })
    await nav.getByRole('link', { name: 'Spend' }).click()
    await expect(page).toHaveURL(/\/spend$/u)
    await expect(page.getByTestId('spend-window-7')).toHaveAttribute('data-state', 'on')
    await expect(nav.getByRole('link', { name: 'Spend' })).toHaveAttribute('data-status', 'active')
    await expect(page.getByTestId('nav-highlight')).toHaveClass(/\bbg-section-spend\/16\b/u)
})

test("30 days' table scrolls in its panel under its column names, and a week's shows whole", async ({ page }) => {
    await page.goto('spend?days=30')
    await settled(page)
    const region = page.getByTestId('spend-table-scroll')
    await expect(page.getByTestId('spend-table').locator('tbody tr')).toHaveCount(30)
    const scrolls = () => region.evaluate((el) => el.scrollHeight > el.clientHeight)
    expect(await scrolls()).toBe(true)

    // Scrolled to the oldest day, the column names stay at the region's top. Within a pixel: a sticky header lands on a
    // fraction of one that differs between runs, and once missed the half pixel `toBeCloseTo(y, 0)` allows by 0.02.
    await region.evaluate((el) => el.scrollTo({ top: el.scrollHeight }))
    const thead = page.getByTestId('spend-table').locator('thead')
    await expect
        .poll(async () => {
            const [head, box] = await Promise.all([thead.boundingBox(), region.boundingBox()])
            return Math.abs((head?.y ?? Number.NaN) - (box?.y ?? Number.NaN))
        })
        .toBeLessThanOrEqual(1)

    await page.getByTestId('spend-window-7').click()
    await expect(page.getByTestId('spend-table').locator('tbody tr')).toHaveCount(7)
    expect(await scrolls()).toBe(false)
})

test("the ticket, PR, and tool tables scroll under their column names, flush with the panel's title", async ({
    page,
}) => {
    await page.goto('spend')
    await settled(page)
    for (const id of ['spend-ticket-table', 'spend-pull-request-table', 'spend-tool-table']) {
        const table = page.getByTestId(id)
        const region = page.getByRole('region').filter({ has: table })
        // The mock's rows fit their regions: shorten one until it scrolls, then scroll it to its end.
        await region.evaluate((el) => {
            el.style.maxHeight = '6rem'
            el.scrollTo({ top: el.scrollHeight })
        })
        // Within a pixel, as the day table's: no strip of the padded region over the names for the rows to show in.
        await expect
            .poll(async () => {
                const [head, box] = await Promise.all([table.locator('thead').boundingBox(), region.boundingBox()])
                return Math.abs((head?.y ?? Number.NaN) - (box?.y ?? Number.NaN))
            })
            .toBeLessThanOrEqual(1)
    }
})

test("each ticket's and PR's own runs, the costliest first, open their pages beside the tickets done", async ({
    page,
}) => {
    await page.goto('spend')
    await settled(page)
    // The mock journal marks no ticket done, so there is nothing to divide the spend by.
    await expect(page.getByTestId('spend-done')).toHaveText('0')
    await expect(page.getByTestId('spend-per-done')).toHaveText('–')
    // Nor does it triage a ticket: no plan was waived.
    await expect(page.getByTestId('spend-waived')).toHaveText('0')
    await expect(page.getByTestId('spend-day-2026-10-08').locator('td').last()).toHaveText('0')

    const tickets = page.getByTestId('spend-ticket-table').locator('tbody tr')
    await expect(tickets).toHaveCount(7)
    // ABC-099's two runs and the two reviews of its PR.
    await expect(tickets.first()).toHaveAttribute('data-testid', 'spend-ticket-ABC-099')
    await expect(tickets.first().locator('td').nth(1)).toHaveText('$3.50')

    const prs = page.getByTestId('spend-pull-request-table').getByTestId('spend-pull-request')
    await expect(prs).toHaveCount(4)
    await expect(prs.last()).toContainText('none')
    await prs.first().getByRole('link', { name: 'acme/web#88', exact: true }).click()
    await expect(page).toHaveURL(/\/pull-requests\/pr\?url=/u)
})

test('the tools whose calls returned the most, by kind, the most first', async ({ page }) => {
    await page.goto('spend')
    await settled(page)
    const tools = page.getByTestId('spend-tool-table').getByTestId('spend-tool')
    await expect(tools).toHaveCount(11)
    // The overseer's PR reads over both mock ticks, then the workers' shell calls.
    await expect(tools.first().getByRole('cell')).toHaveText(['overseer', '25', '0', '325.0k', '81.3k'])
    await expect(tools.first().getByRole('rowheader')).toHaveText('github_pull_request_read')
    await expect(tools.nth(1).getByRole('rowheader')).toHaveText('bash')
    await expect(tools.nth(1).getByRole('cell')).toHaveText(['workers', '119', '11', '279.0k', '69.8k'])
})

test.describe('on a wide monitor', () => {
    test.use({ viewport: { width: 1440, height: 900 } })

    test('30 days name every fifth day whole, centered under its bar, and a week every day', async ({ page }) => {
        await page.goto('spend?days=30')
        await settled(page)
        await expectSpendAxisWhole(page, 6)
        await page.getByTestId('spend-window-7').click()
        await expect(page.getByTestId('spend-chart').getByTestId(/^spend-bar-/u)).toHaveCount(7)
        await expectSpendAxisWhole(page, 7)
    })
})

test("the dearest day's total is over its bar, which stops short of the chart's top", async ({ page }) => {
    await page.goto('spend?days=30')
    await settled(page)
    // The mock prices today alone: its total is the dearest.
    const total = await page.getByTestId('spend-day-2026-10-08').locator('td').nth(8).textContent()
    const peak = page.getByTestId('spend-bar-2026-10-08').getByTestId('spend-peak')
    await expect(peak).toHaveText(total ?? '')
    await expect(peak).toHaveText(/^\$\d+\.\d\d$/u)
    await expect(page.getByTestId('spend-peak')).toHaveCount(1)

    const [bar, label, top] = await Promise.all([
        page.getByTestId('spend-bar-2026-10-08').boundingBox(),
        peak.boundingBox(),
        page.getByTestId('spend-bar-2026-10-08').getByTestId('spend-segment-reviews').boundingBox(),
    ])
    if (bar === null || label === null || top === null) {
        throw new Error("the dearest day's bar is not drawn")
    }
    // A fifth of the plot is headroom: the label sits in it, inside the plot, and the bar's top under the label.
    expect(label.y).toBeGreaterThanOrEqual(bar.y)
    expect(top.y).toBeGreaterThanOrEqual(label.y + label.height - 1)
    expect(top.y - bar.y).toBeGreaterThanOrEqual(bar.height * 0.2 - 1)
})

test('a week of one priced day draws one narrow bar, its segments apart, and the days without cost as stubs', async ({
    page,
}) => {
    await page.goto('spend')
    await settled(page)
    const chart = page.getByTestId('spend-chart')
    const bar = chart.getByTestId('spend-bar-2026-10-08')
    // The cap, 3rem: the one priced day of the week is no slab.
    expect((await bar.boundingBox())?.width ?? Number.POSITIVE_INFINITY).toBeLessThanOrEqual(48.5)
    // The other six days are a 1px stub each, on the baseline the priced bar stands on.
    const stubs = chart.getByTestId('spend-stub')
    await expect(stubs).toHaveCount(6)
    // One read of the layout for the bar and every stub: read apart, a shift above the chart between reads moves one
    // and not the other.
    const { barBottom, stubBoxes } = await chart.evaluate((el) => ({
        barBottom: el.querySelector('[data-testid="spend-bar-2026-10-08"]')?.getBoundingClientRect().bottom ?? 0,
        stubBoxes: [...el.querySelectorAll('[data-testid="spend-stub"]')].map((stub) => {
            const box = stub.getBoundingClientRect()
            return { height: box.height, bottom: box.bottom }
        }),
    }))
    expect(stubBoxes).toHaveLength(6)
    for (const box of stubBoxes) {
        expect(box.height).toBe(1)
        expect(Math.abs(box.bottom - barBottom)).toBeLessThanOrEqual(1)
    }

    // Every series with a cost that day is at least 2px tall, idle's few cents included, and 2px from the next.
    const segments = (
        await bar.getByTestId(/^spend-segment-/u).evaluateAll((elements) =>
            elements.map((el) => {
                const box = el.getBoundingClientRect()
                return { top: box.top, bottom: box.bottom }
            }),
        )
    ).toSorted((a, b) => a.top - b.top)
    expect(segments).toHaveLength(6)
    for (const [i, segment] of segments.entries()) {
        expect(segment.bottom - segment.top).toBeGreaterThanOrEqual(1.99)
        const below = segments[i + 1]
        if (below !== undefined) {
            expect(Math.abs(below.top - segment.bottom - 2)).toBeLessThanOrEqual(1)
        }
    }
})

test('a window where nothing reported a cost says so once in By day, and claims nothing in Totals', async ({
    page,
}) => {
    // The mock's own window, with every cost and count taken out of it.
    await page.route('**/api/spend/breakdown*', async (route) => {
        const response = await route.fetch()
        const found = (await response.json()) as Record<string, unknown> & {
            per_day: { costs: Costs; done: number }[]
            totals: Costs
            ticks: { ticks: number; cost_usd: number | null }[]
            unpriced: { runs: number; unpriced: number }[]
        }
        for (const day of found.per_day) {
            day.costs = nothing(day.costs)
            day.done = 0
        }
        for (const group of found.ticks) {
            group.ticks = 0
            group.cost_usd = null
        }
        for (const kind of found.unpriced) {
            kind.runs = 0
            kind.unpriced = 0
        }
        const json = {
            ...found,
            totals: nothing(found.totals),
            woken: [],
            idle_share: null,
            idle_ticks: [],
            tickets: [],
            pull_requests: [],
            tools: [],
            done: 0,
            per_done: null,
        }
        await route.fulfill({ response, json })
    })
    await page.goto('spend')
    await settled(page)
    const byDay = page.getByTestId('spend-by-day')
    await expect(byDay.getByText('no run reported a cost in these 7 days')).toBeVisible()
    await expect(byDay.getByTestId('spend-chart')).toHaveCount(0)
    await expect(byDay.getByTestId('spend-legend')).toHaveCount(0)
    await expect(byDay.getByTestId('spend-table')).toHaveCount(0)
    await expect(page.getByTestId('spend-idle-share')).toHaveCount(0)
    await expect(page.getByTestId('spend-ticks').getByText('no tick ended in these 7 days')).toBeVisible()
    await expect(page.getByTestId('spend-groups')).toHaveCount(0)
})

/** The same costs, every one unreported. */
function nothing(costs: Costs): Costs {
    return Object.fromEntries(Object.keys(costs).map((key) => [key, null]))
}
