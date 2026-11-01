import { expect, test } from '@playwright/test'

import { expectSpendAxisWhole, settled, signIn } from './helpers.ts'

/** A spend breakdown's costs, by name. */
type Costs = Record<string, number | null>

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the rail's counters open the spend page over their own windows, whose totals agree with them", async ({
    page,
}) => {
    await page.goto('attention')
    await settled(page)
    const day = await page.getByTestId('rail-spend-24h').textContent()
    const month = await page.getByTestId('rail-spend-30d').textContent()

    await page.getByTestId('rail-spend-link-24h').click()
    await expect(page).toHaveURL(/\/reports\/spend\?hours=24$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Spend')
    await expect(page.getByTestId('spend-window-24h')).toHaveAttribute('data-state', 'on')
    await expect(page.getByTestId('spend-chart').getByTestId(/^spend-bar-/u)).toHaveCount(24)
    // Every run in the mock journal started within the 24 hours, so the window's total is the rail's.
    await expect(page.getByTestId('spend-total-total')).toHaveText(day ?? '')

    await page.goto('attention')
    await page.getByTestId('rail-spend-link-30d').click()
    await expect(page).toHaveURL(/\/reports\/spend\?days=30$/u)
    await expect(page.getByTestId('spend-window-30')).toHaveAttribute('data-state', 'on')
    await expect(page.getByTestId('spend-chart').getByTestId(/^spend-bar-/u)).toHaveCount(30)
    // Every run in the mock journal started within the 30 days, so the window's total is the rail's.
    await expect(page.getByTestId('spend-total-total')).toHaveText(month ?? '')
})

test('the window switches from the toggle, and idle spend is its own series with its ticks linked', async ({
    page,
}) => {
    await page.goto('reports/spend?days=30')
    await settled(page)
    await page.getByTestId('spend-window-7').click()
    await expect(page).toHaveURL(/\/reports\/spend$/u)
    await expect(page.getByTestId('spend-table').locator('tbody tr')).toHaveCount(7)

    // The mock's second tick was idle: its overseer's cost is the idle series, and the share of the overseer's.
    await expect(page.getByTestId('spend-total-idle')).toHaveText('$0.31')
    await expect(page.getByTestId('spend-total-overseer')).toHaveText('$0.59')
    await expect(page.getByTestId('spend-idle-share')).toContainText('53%')
    await expect(page.getByTestId('spend-groups-idle')).toContainText('1')
    await expect(page.getByTestId('spend-woken-table-timer')).toBeVisible()
    // Each tick table splits off the ticks that ran no overseer: the mock's every tick ran one.
    for (const table of ['spend-groups', 'spend-woken-table']) {
        await expect(page.getByTestId(table).getByRole('columnheader', { name: 'no overseer' })).toBeVisible()
    }
    await expect(page.getByTestId('spend-groups-idle').getByRole('cell').last()).toHaveText('0')
    const today = page.getByTestId('spend-day-2026-10-08')
    await expect(today.locator('td').first()).toHaveText('$0.31')

    // The Ticks panel links the ticks page's idle ticks, where the mock's one idle tick is all there is.
    await page.getByTestId('spend-idle-link').click()
    await expect(page).toHaveURL(/\/workspace\/ticks\?idle=true$/u)
    const ticks = page.getByTestId('ticks')
    await expect(ticks.getByTestId(/^tick-\d+$/u)).toHaveCount(1)
    await ticks.getByRole('link', { name: 'tick:2' }).click()
    await expect(page).toHaveURL(/\/workspace\/ticks\/2$/u)
})

test('the ticks page keeps its idle ticks from its filter, and every tick again from all', async ({ page }) => {
    await page.goto('workspace/ticks')
    await settled(page)
    const filter = page.getByTestId('ticks-filter')
    await expect(page.getByTestId('ticks').getByTestId(/^tick-\d+$/u)).toHaveCount(2)
    await filter.getByRole('link', { name: 'idle' }).click()
    await expect(page).toHaveURL(/\/workspace\/ticks\?idle=true$/u)
    await expect(page.getByTestId('ticks').getByTestId(/^tick-\d+$/u)).toHaveCount(1)
    await filter.getByRole('link', { name: 'all' }).click()
    await expect(page).toHaveURL(/\/workspace\/ticks$/u)
    await expect(page.getByTestId('ticks').getByTestId(/^tick-\d+$/u)).toHaveCount(2)
})

test("each series has one name in the totals, the legend, and the table, and the description is the window's", async ({
    page,
}) => {
    await page.goto('reports/spend')
    await settled(page)
    // The window's state, with what the page holds on the title's hover.
    const total = await page.getByTestId('spend-total-total').textContent()
    await expect(page.locator('main header p')).toHaveText(`${total ?? ''} over 7 days · no tickets done`)
    await expect(page.getByRole('heading', { level: 1 })).toHaveAttribute('title', /canopy spend --days N/u)

    const series = [
        'idle ticks',
        'overseer',
        'workers',
        'plans',
        'chores',
        'reviews',
        'tasks',
        'dry runs',
        'outside canopy',
    ]
    await expect(page.getByTestId('spend-legend').getByRole('listitem')).toHaveText(series)
    await expect(page.getByTestId('spend-table').locator('thead th')).toHaveText(['day', ...series, 'total', 'done'])
    // The totals name the overseer's whole before idle ticks' part of it, as canopy spend's columns do. The mock's
    // week has no dry run, and its loop never read the sessions outside canopy: the line under the tiles says so.
    const totals = page.getByTestId('spend-totals').locator('dt')
    await expect(totals).toHaveText([
        'total',
        'overseer',
        'idle ticks',
        'workers',
        'plans',
        'chores',
        'reviews',
        'tasks',
        'tickets done',
        'per ticket done',
    ])
    await expect(page.getByTestId('spend-total-folded')).toHaveText(
        'No dry runs, sessions outside canopy not read yet.',
    )
    await expect(page.getByText('other ticks')).toHaveCount(0)
})

test('24 hours read by the hour, each named by its time and in full in the table', async ({ page }) => {
    await page.goto('reports/spend')
    await settled(page)
    await page.getByTestId('spend-window-24h').click()
    await expect(page).toHaveURL(/\/reports\/spend\?hours=24$/u)
    await expect(page.getByTestId('spend-by-day').getByText('By hour')).toBeVisible()
    await expect(page.getByTestId('spend-table').locator('tbody tr')).toHaveCount(24)
    await expect(page.getByTestId('spend-table').locator('thead th').first()).toHaveText('hour')
    await expect(page.locator('main header p')).toContainText(' over 24 hours · ')
    // The newest hour first in the table, stamped with its day, and last on the axis by its time alone, both in the
    // browser's zone.
    await expect(page.getByTestId('spend-table').locator('tbody th').first()).toHaveText(/^Oct \d+ \d{2}:00$/u)
    await expect(
        page
            .getByTestId('spend-chart')
            .getByTestId(/^spend-axis-/u)
            .last(),
    ).toHaveText(/^\d{2}:00$/u)
    await expectSpendAxisWhole(page, 5)

    await page.getByTestId('spend-window-7').click()
    await expect(page).toHaveURL(/\/reports\/spend$/u)
    await expect(page.getByTestId('spend-by-day').getByText('By day')).toBeVisible()
})

test("30 days read by the week from By day's pitch, which a shorter window does not offer", async ({ page }) => {
    await page.goto('reports/spend?days=30')
    await settled(page)
    const byDay = page.getByTestId('spend-by-day')
    await byDay.getByTestId('spend-pitch-week').click()
    await expect(page).toHaveURL(/\/reports\/spend\?days=30&pitch=week$/u)
    await expect(byDay.getByText('By week', { exact: true })).toBeVisible()
    // The mock's 30 days end on a Thursday, so they start on a Wednesday: five weeks, part ones at both ends.
    await expect(page.getByTestId('spend-chart').getByTestId(/^spend-bar-/u)).toHaveCount(5)
    await expect(page.getByTestId('spend-table').locator('thead th').first()).toHaveText('week')
    await expect(page.getByTestId('spend-table').locator('tbody th').first()).toHaveText(/^week of Oct \d+$/u)
    // The week's window draws its days whatever the pitch kept in the search.
    await page.getByTestId('spend-window-7').click()
    await expect(byDay.getByText('By day', { exact: true })).toBeVisible()
    await expect(byDay.getByTestId('spend-pitch-week')).toHaveCount(0)
    await expect(page.getByTestId('spend-chart').getByTestId(/^spend-bar-/u)).toHaveCount(7)
})

test('a window the page does not offer reads as the week', async ({ page }) => {
    await page.goto('reports/spend?days=9')
    await settled(page)
    await expect(page.getByTestId('spend-window-7')).toHaveAttribute('data-state', 'on')
    await expect(page.getByTestId('spend-table').locator('tbody tr')).toHaveCount(7)
})

test('each total says how it moved since the window before, which a line under them names once', async ({ page }) => {
    await page.goto('reports/spend')
    await settled(page)
    // The mock's week cost more than the week before it, whose history spent less and landed three tickets.
    await expect(page.getByTestId('spend-total-total-delta')).toHaveText(/^\+\$/u)
    await expect(page.getByTestId('spend-done-delta')).toHaveText('−3')
    await expect(page.getByTestId('spend-against')).toHaveText('Each change under a figure is on the 7 days before.')
    await page.getByTestId('spend-window-24h').click()
    await expect(page.getByTestId('spend-against')).toHaveText('Each change under a figure is on the 24 hours before.')
})

test("Reports opens the spend page on the week, Spend's item marked under it", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const nav = page.getByRole('navigation', { name: 'Main' })
    await nav.getByRole('link', { name: 'Reports' }).click()
    await page.getByTestId('reports-spend-link').click()
    await expect(page).toHaveURL(/\/reports\/spend$/u)
    await expect(page.getByTestId('spend-window-7')).toHaveAttribute('data-state', 'on')
    await expect(nav.getByRole('link', { name: 'Spend' })).toHaveAttribute('data-status', 'active')
    await expect(nav.getByRole('link', { name: 'Reports' })).not.toHaveAttribute('data-status', 'active')
    // The highlight on a page under Reports is in Reports' color.
    await expect(page.getByTestId('nav-highlight')).toHaveClass(/\bbg-section-reports\/24\b/u)
})

test("30 days' table opens to scroll in its panel under its column names, and a week's shows whole", async ({
    page,
}) => {
    await page.goto('reports/spend?days=30')
    await settled(page)
    // The table arrives folded under the chart, its row count on its button.
    await expect(page.getByTestId('spend-table-scroll')).toHaveCount(0)
    await page.getByRole('button', { name: 'Show 30 days as a table' }).click()
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

    // Another window keeps the table open, its count on its button.
    await page.getByTestId('spend-window-7').click()
    await expect(page.getByRole('button', { name: 'Hide 7 days as a table' })).toBeVisible()
    await expect(page.getByTestId('spend-table').locator('tbody tr')).toHaveCount(7)
    expect(await scrolls()).toBe(false)
})

test("the ticket, PR, model, and tool tables scroll under their column names, flush with the panel's title", async ({
    page,
}) => {
    await page.goto('reports/spend')
    await settled(page)
    for (const id of ['spend-ticket-table', 'spend-pull-request-table', 'spend-model-table', 'spend-tool-table']) {
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
    await page.goto('reports/spend')
    await settled(page)
    // The mock journal marks no ticket done, so there is nothing to divide the spend by.
    await expect(page.getByTestId('spend-done')).toHaveText('0')
    await expect(page.getByTestId('spend-per-done')).toHaveText('–')
    await expect(page.getByTestId('spend-day-2026-10-08').locator('td').last()).toHaveText('0')

    const tickets = page.getByTestId('spend-ticket-table').locator('tbody tr')
    await expect(tickets).toHaveCount(7)
    // ABC-099's two runs and the two reviews of its PR.
    await expect(tickets.first()).toHaveAttribute('data-testid', 'spend-ticket-ABC-099')
    await expect(tickets.first().locator('td').nth(1)).toHaveText('$3.50')

    const prs = page.getByTestId('spend-pull-request-table').getByTestId('spend-pull-request')
    await expect(prs).toHaveCount(5)
    await expect(prs.last()).toContainText('none')
    await prs.first().getByRole('link', { name: 'acme/web#88', exact: true }).click()
    await expect(page).toHaveURL(/\/pull-requests\/pr\?url=/u)
})

test("the tools whose calls returned the most, every kind's summed, or one kind's from the header", async ({
    page,
}) => {
    await page.goto('reports/spend')
    await settled(page)
    const tools = page.getByTestId('spend-tool-table').getByTestId('spend-tool')
    // Five tools, each once whatever kinds called it.
    await expect(tools).toHaveCount(5)
    // The PR reads lead, the overseer's over both mock ticks and a worker's, then every kind's shell calls.
    await expect(tools.first().getByRole('rowheader')).toHaveText('github_pull_request_read')
    await expect(tools.first().getByRole('cell')).toHaveText(['27', '0', '346.0k', '86.5k'])
    await expect(tools.nth(1).getByRole('rowheader')).toHaveText('bash')
    await expect(tools.nth(1).getByRole('cell')).toHaveText(['149', '13', '325.1k', '81.3k'])
    await expect(page.getByTestId('spend-tool_kind').getByRole('link', { name: 'all' })).toHaveAttribute(
        'data-selected',
        'true',
    )

    await page.getByTestId('spend-tool_kind').getByRole('link', { name: 'workers' }).click()
    await expect(page).toHaveURL(/\/reports\/spend\?tool_kind=workers$/u)
    await expect(tools.first().getByRole('rowheader')).toHaveText('bash')
    await expect(tools.first().getByRole('cell')).toHaveText(['119', '11', '279.0k', '69.8k'])
    // The other filter, and the window, keep what they show.
    await expect(page.getByTestId('spend-model_kind').getByRole('link', { name: 'all' })).toHaveAttribute(
        'data-selected',
        'true',
    )
    await page.getByTestId('spend-window-30').click()
    await expect(page).toHaveURL(/\/reports\/spend\?.*tool_kind=workers/u)
    await expect(tools.first().getByRole('rowheader')).toHaveText('bash')
})

test("what the runs spent on each model, every kind's summed, or one kind's from the header", async ({ page }) => {
    await page.goto('reports/spend')
    await settled(page)
    // Four models, each counted once whatever kinds it served.
    await expect(page.getByTestId('spend-model-count')).toHaveText('4')
    const models = page.getByTestId('spend-model-table').getByTestId('spend-model')
    await expect(models).toHaveCount(6)
    // Sonnet served the overseer and the workers both: one row, the dearest.
    await expect(models.first().getByRole('rowheader')).toHaveText('anthropic/claude-sonnet-4-5')
    // The runs no session named a model for sit last, every kind's together: those canopy has yet to read, then those
    // it read that named none.
    await expect(models.nth(4).getByRole('rowheader')).toHaveText('unread')
    await expect(models.last().getByRole('rowheader')).toHaveText('none: no session named one')

    await page.getByTestId('spend-model_kind').getByRole('link', { name: 'workers' }).click()
    await expect(page).toHaveURL(/\/reports\/spend\?model_kind=workers$/u)
    await expect(models).toHaveCount(4)
    await expect(models.nth(1).getByRole('rowheader')).toHaveText('anthropic/claude-opus-4-1')
    // Spent, then per run: one run, so the same.
    await expect(models.nth(1).getByRole('cell')).toHaveText(['1', '23', '$1.65', '$1.65'])
    // Run 40's failed read among them, and run 42, which no tick has read yet.
    await expect(models.nth(2).getByRole('rowheader')).toHaveText('unread')
    await expect(models.nth(2).getByRole('cell')).toHaveText(['5', '–', '$2.53', '$0.51'])
    // ABC-099's two feedback plan runs, which reported no session, and no cost.
    await expect(models.last().getByRole('rowheader')).toHaveText('none: no session named one')
    await expect(models.last().getByRole('cell')).toHaveText(['2', '–', '–', '–'])
    // What the unread row holds is said in the header, since it sits near the end and shrinks as ticks read it.
    await expect(page.getByTestId('spend-model-unread')).toHaveText(/^\d+% unread$/u)
})

test("a model's row opens the runs page on the runs of its kind it served", async ({ page }) => {
    await page.goto('reports/spend?model_kind=workers')
    await settled(page)
    await page.getByTestId('spend-model-table').getByRole('link', { name: 'anthropic/claude-opus-4-1' }).click()
    await expect(page).toHaveURL(/\/workspace\/runs\?model=anthropic(%2F|\/)claude-opus-4-1&kind=worker$/u)
    // Run 39, which switched from opus to sonnet partway, and the one opus run of the spring (history.py) still among
    // the 50 that ended last, which is all the runs page lists: September's plan runs (plan_approvals.py) came after.
    await expect(page.getByTestId('runs-count')).toHaveText('2')
    await expect(page.getByTestId('run-39')).toBeVisible()
    // The model's picker, as the repository's, offers every model the runs listed name, and takes it off.
    await page.getByRole('button', { name: 'Filter by model: anthropic/claude-opus-4-1' }).click()
    const models = page.getByRole('listbox', { name: 'Models' })
    await expect(models.getByRole('option', { name: 'openai/gpt-5' })).toBeVisible()
    await models.getByRole('option', { name: 'every model' }).click()
    await expect(page).toHaveURL(/\/workspace\/runs\?kind=worker$/u)
    await expect(page.getByRole('button', { name: 'Filter by model: every model' })).toBeVisible()
})

test("under every kind, a model's row opens its runs of every kind, a review's among them", async ({ page }) => {
    await page.goto('reports/spend')
    await settled(page)
    // The mock's reviewer runs on gpt-5, which served no worker.
    await page.getByTestId('spend-model-table').getByRole('link', { name: 'openai/gpt-5' }).click()
    await expect(page).toHaveURL(/\/workspace\/runs\?model=openai(%2F|\/)gpt-5$/u)
    await expect(page.getByText(/no recent runs on/u)).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'review:4' })).toBeVisible()
})

test("a ticket's worker models, beside the workspace's, open By model for the ticket", async ({ page }) => {
    await page.goto('tickets/ABC-099')
    // Opus and sonnet both served its workers; sonnet's other runs are the workspace's, the reviewer's gpt-5 is not.
    const line = page.getByTestId('ticket-model-spend')
    await expect(line).toContainText('claude-opus-4-1: 1 run, $1.65/run · workspace $1.65/run')
    await expect(line).toContainText('claude-sonnet-4-5: 1 run, $0.66/run · workspace $1.54/run')
    await expect(line).not.toContainText('gpt-5')
    await line.getByRole('link', { name: 'worker spend, 30 days' }).click()
    await expect(page).toHaveURL(/\/reports\/spend\?days=30&ticket=ABC-099$/u)
    await settled(page)

    const kinds = page.getByTestId('spend-model_kind')
    await expect(kinds.getByRole('link', { name: 'workers' })).toHaveAttribute('data-selected', 'true')
    const models = page.getByTestId('spend-model-table').getByTestId('spend-model')
    // Its two models, then its resume no tick has read yet and its feedback plan, which reported no session.
    await expect(models).toHaveCount(4)
    await expect(models.nth(1).getByRole('rowheader')).toHaveText('anthropic/claude-sonnet-4-5')
    await expect(models.nth(1).getByRole('cell')).toHaveText(['1', '41', '$0.66', '$0.66', '$1.54'])
    await expect(models.nth(2).getByRole('rowheader')).toHaveText('unread')
    await expect(models.last().getByRole('rowheader')).toHaveText('none: no session named one')
    // Every kind of its runs, the reviewer's among them, then every ticket's again, at the kind chosen.
    await kinds.getByRole('link', { name: 'all' }).click()
    await expect(page).toHaveURL(/model_kind=all/u)
    await expect(models.getByRole('rowheader', { name: 'openai/gpt-5' })).toBeVisible()
    await page.getByTestId('spend-model-ticket').getByRole('link', { name: 'every ticket' }).click()
    await expect(page).toHaveURL(/\/reports\/spend\?days=30$/u)
    await expect(page.getByTestId('spend-model-table').locator('thead th')).toHaveCount(5)
})

test("the overseer's models are not linked, as the runs page lists no tick by model", async ({ page }) => {
    await page.goto('reports/spend?model_kind=overseer')
    await settled(page)
    const table = page.getByTestId('spend-model-table')
    await table.getByTestId('spend-model-unlisted').first().hover()
    await expect(page.getByRole('tooltip')).toContainText(/lists no overseer tick/u)
    await expect(table.getByRole('link')).toHaveCount(0)
})

test.describe('on a wide monitor', () => {
    test.use({ viewport: { width: 1440, height: 900 } })

    test('30 days name every fifth day whole, centered under its bar, and a week every day', async ({ page }) => {
        await page.goto('reports/spend?days=30')
        await settled(page)
        await expectSpendAxisWhole(page, 6)
        await page.getByTestId('spend-window-7').click()
        await expect(page.getByTestId('spend-chart').getByTestId(/^spend-bar-/u)).toHaveCount(7)
        await expectSpendAxisWhole(page, 7)
    })
})

test("the dearest day's total is over its bar, which stops short of the chart's top", async ({ page }) => {
    await page.goto('reports/spend?days=30')
    await settled(page)
    // The mock prices today alone: its total is the dearest.
    const total = await page.getByTestId('spend-day-2026-10-08').locator('td').nth(9).textContent()
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
    await page.goto('reports/spend')
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
    expect(segments).toHaveLength(7)
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
    await page.goto('reports/spend')
    await settled(page)
    const byDay = page.getByTestId('spend-by-day')
    await expect(byDay.getByText('no run reported a cost in these 7 days')).toBeVisible()
    await expect(byDay.getByTestId('spend-chart')).toHaveCount(0)
    await expect(byDay.getByTestId('spend-legend')).toHaveCount(0)
    await expect(byDay.getByTestId('spend-table')).toHaveCount(0)
    await expect(page.getByTestId('spend-idle-share')).toHaveCount(0)
    await expect(page.getByTestId('spend-ticks').getByText('no tick ended in these 7 days')).toBeVisible()
    await expect(page.getByTestId('spend-groups')).toHaveCount(0)
    // A live event from another test's writes refetches the breakdown, which can still be in the handler when the page
    // closes and disposes its response: drop it, since it comes after everything this test checks.
    await page.unrouteAll({ behavior: 'ignoreErrors' })
})

/** The same costs, every one unreported. */
function nothing(costs: Costs): Costs {
    return Object.fromEntries(Object.keys(costs).map((key) => [key, null]))
}

test("the header's budget says the month is headed over, the numbers on hover, and opens the spend page", async ({
    page,
}) => {
    // Wide enough for the percent beside the icon; narrower, the icon stands alone.
    await page.setViewportSize({ width: 1600, height: 800 })
    await page.goto('attention')
    await settled(page)
    // The mock's budget is $40, and its month's pace passes it.
    const readout = page.getByTestId('budget-readout')
    await expect(readout).toHaveText('39%')
    await expect(readout).toHaveAttribute('data-state', 'headed')
    await expect(readout).toHaveAccessibleName(/^Headed over: \$15\.76 of \$40 \(39%\), on pace for \$/u)
    await readout.hover()
    const card = page.getByTestId('budget-card')
    await expect(card).toContainText('Headed over')
    await expect(card).toContainText('39%, $15.76 of $40')
    await readout.click()
    await expect(page).toHaveURL(/\/reports\/spend$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Spend')
})

test('this month reads against the budget whatever the window, and is headed over at its pace', async ({ page }) => {
    await page.goto('reports/spend?hours=24')
    await settled(page)
    // The mock's budget is $40, and every run in its journal started in October.
    const budget = page.getByTestId('spend-budget')
    await expect(budget).toContainText('October 2026')
    await expect(page.getByTestId('spend-budget-text')).toContainText('Headed over')
    await expect(page.getByTestId('spend-budget-text')).toHaveText('Headed over: $15.76 of $40 (39%)')
    await expect(page.getByTestId('spend-budget-pace')).toHaveText(/^On pace to spend \$[\d.]+ of \$40\.$/u)
    // The mock's loop never read the runtime's sessions, so the month is canopy's runs alone, and says so.
    await expect(page.getByTestId('spend-budget-parts')).toHaveText(
        "Canopy's runs $15.76. Sessions outside canopy count once canopy loop has read them.",
    )
    await page.getByTestId('spend-window-30').click()
    await expect(page.getByTestId('spend-budget-text')).toContainText('$15.76 of $40 (39%)')
    // Nor does the panel of every session list any: it says why.
    await expect(page.getByTestId('spend-sessions')).toContainText(
        "canopy loop has not read the runtime's sessions yet",
    )
    // Nor do the totals give them a tile of a dash: the line under the tiles says they wait on the loop.
    await expect(page.getByTestId('spend-total-outside')).toHaveCount(0)
    await expect(page.getByTestId('spend-total-folded')).toContainText('sessions outside canopy not read yet')
    // The mock alerts at half and four fifths of the budget too: each a tick over the bar labelled with its percent,
    // and the mark across it labelled with the day.
    await expect(page.getByTestId('spend-budget-alert-50')).toHaveText('50%')
    await expect(page.getByTestId('spend-budget-alert-80')).toHaveText('80%')
    await expect(page.getByTestId('spend-budget-day')).toHaveText(/^day \d+ of 31$/u)
    await expect(page.getByTestId('spend-budget-alerts')).toContainText('hears at 50%, 80%, and 100%.')
})

test("each kind's first calls by week mark where a runtime or snapshot changed, a chore's or model's apart", async ({
    page,
}) => {
    await page.goto('reports/spend?days=30')
    await settled(page)
    const panel = page.getByTestId('spend-first-calls')
    const kinds = panel.getByTestId('spend-first_kind')
    // The overseer first, as canopy spend orders the kinds; no `all`, since kinds' prefixes do not sum.
    await expect(kinds.getByRole('link')).toHaveText(['overseer', 'workers', 'plans', 'chores', 'reviews', 'tasks'])
    await expect(kinds.getByRole('link', { name: 'overseer' })).toHaveAttribute('data-selected', 'true')

    await kinds.getByRole('link', { name: 'workers' }).click()
    await expect(page).toHaveURL(/\/reports\/spend\?days=30&first_kind=workers$/u)
    // The history's September: the week of a prompt change read little from the cache, and the runtime moved the next.
    await expect(panel.getByTestId(/^first-call-bar-/u)).toHaveCount(5)
    await expect(panel.getByTestId('first-call-bar-2026-W39')).toHaveText('57%')
    await expect(panel.getByTestId('first-call-marker')).toHaveCount(2)
    await expect(panel.getByRole('list', { name: 'What changed' }).getByRole('listitem')).toHaveText([
        'Week of Sep 21: snapshot a81d2c4e9f306b17',
        'Week of Sep 28: runtime 1.0.104',
    ])
    await expect(panel.getByTestId('first-call-table').locator('tbody tr').first()).toHaveAttribute(
        'data-testid',
        'first-call-week-2026-W41',
    )

    // A kind's series: all its runs, then each chore's and each model's.
    await kinds.getByRole('link', { name: 'chores' }).click()
    const series = panel.getByTestId('spend-first-series')
    await expect(series.getByRole('link')).toHaveText([
        'all runs',
        'build-health',
        'deps',
        'anthropic/claude-haiku-4-5',
    ])
    await series.getByRole('link', { name: 'deps' }).click()
    await expect(page).toHaveURL(/first_series=chore%3Adeps/u)
    await expect(series.getByRole('link', { name: 'deps' })).toHaveAttribute('data-selected', 'true')
    await expect(panel.getByTestId('first-call-table').locator('tbody tr')).toHaveCount(1)

    // Another kind starts on all its runs; the week holds the fixtures' alone, one bar and nothing changed.
    await kinds.getByRole('link', { name: 'workers' }).click()
    await expect(page).not.toHaveURL(/first_series/u)
    await page.getByTestId('spend-window-7').click()
    await expect(panel.getByTestId(/^first-call-bar-/u)).toHaveCount(1)
    await expect(panel.getByRole('list', { name: 'What changed' })).toHaveCount(0)
})
