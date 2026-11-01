import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockReportMonth, mockReportTicket, mockReportTokens } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { HealthCounts, HealthReport, MonthlyReport } from '@/api/types'

import { Route } from './reports.index'

afterEach(() => {
    cleanup()
})

const NO_RUNS: HealthCounts = { overseer: 0, workers: 0, plans: 0, chores: 0, reviews: 0, tasks: 0 }

// A year read whole, its first five months empty: April's workers and October's, with October's overseer and the
// sessions outside canopy, two tickets landed in September and October, and their medians.
const YEAR: MonthlyReport = {
    sessions_read_at: null,
    months: [
        ...['2025-11', '2025-12', '2026-01', '2026-02', '2026-03'].map((name) => mockReportMonth(name, null)),
        mockReportMonth('2026-04', 4, {
            runs: 2,
            kinds: [{ kind: 'workers', runs: 2, cost_usd: 4, tokens: mockReportTokens }],
        }),
        ...['2026-05', '2026-06', '2026-07', '2026-08'].map((name) => mockReportMonth(name, null)),
        mockReportMonth('2026-09', 3, {
            runs: 1,
            landed: [mockReportTicket('ABC-1')],
            median_iterations: 2,
            median_hours_to_land: 30,
        }),
        mockReportMonth('2026-10', 10, {
            runs: 5,
            kinds: [
                { kind: 'overseer', runs: 2, cost_usd: 2, tokens: mockReportTokens },
                { kind: 'workers', runs: 3, cost_usd: 6, tokens: mockReportTokens },
            ],
            outside: { sessions: 1, cost_usd: 2, tokens: mockReportTokens },
            models: [
                { model: 'anthropic/claude-opus', runs: 3, replies: 9, cost_usd: 6, unread: false },
                { model: 'anthropic/claude-haiku', runs: 2, replies: 4, cost_usd: 2, unread: false },
            ],
            landed: [
                mockReportTicket('ABC-2', {
                    cost_usd: 5,
                    pull_requests: ['https://github.com/acme/web/pull/7'],
                    merged_at: '2026-10-04T10:00:00Z',
                }),
            ],
            pull_requests: 1,
            median_iterations: 1,
            median_hours_to_land: 20,
        }),
    ],
}

// The last 30 days' health: 2 of 10 runs failed, both on the last day.
const HEALTH: HealthReport = {
    days: 30,
    since: '2026-09-09T00:00:00Z',
    until: '2026-10-09T00:00:00Z',
    per_day: [
        { day: '2026-10-07', start: '2026-10-07T00:00:00Z', ended: { ...NO_RUNS, workers: 4 }, failed: NO_RUNS },
        {
            day: '2026-10-08',
            start: '2026-10-08T00:00:00Z',
            ended: { ...NO_RUNS, workers: 6 },
            failed: { ...NO_RUNS, workers: 2 },
        },
    ],
    previous: {
        since: '2026-08-10T00:00:00Z',
        until: '2026-09-09T00:00:00Z',
        runs_ended: 0,
        failed: 0,
        failed_cost_usd: null,
    },
    outcomes: [],
    causes: [],
    durations: [],
    failures: [],
    refusals: [],
    unpriced: [],
}

/** The reports page at `path`, its year already read as `YEAR`, and of the cards' reports Health's alone. */
async function renderPage(path = '/reports') {
    // Nothing reads the server: the reports are the ones set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.monthlyReport(12), YEAR)
    client.setQueryData(keys.healthReport(30), HEALTH)
    const root = createRootRoute()
    const page = Route.update({ id: '/reports/', path: '/reports', getParentRoute: () => root } as never)
    // Where the cards go, so the router can build their links.
    const pages = ['spend', 'checklist', 'health', 'ci', 'reviews', 'plans'].map((name) =>
        createRoute({ getParentRoute: () => root, path: `/reports/${name}` }),
    )
    const router = createRouter({
        routeTree: root.addChildren([page, ...pages]),
        history: createMemoryHistory({ initialEntries: [path] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
}

describe('the reports page', () => {
    it("heads the page with a card for each report, its 30 days as the page's line, a link with its hint", async () => {
        await renderPage()
        const cards = await screen.findByRole('navigation', { name: 'Report pages' })
        expect(
            within(cards)
                .getAllByRole('link')
                .map((link) => link.getAttribute('href')),
        ).toEqual([
            '/reports/spend?days=30',
            '/reports/checklist?days=30',
            '/reports/health?days=30',
            '/reports/ci?days=30',
            '/reports/reviews?days=30',
            '/reports/plans?days=30',
        ])
        const health = screen.getByTestId('reports-card-health')
        expect(health.getAttribute('title')).toBe(
            "How the last days' runs ended, the newest failures, and what the guards refused",
        )
        expect(screen.getByTestId('reports-card-health-line').textContent).toBe('2 of 10 runs failed over 30 days')
        // Its failures by day drawn as a line, a point a day.
        expect(within(health).getByTestId('reports-card-health-trend')).toBeTruthy()
        // A report still being read holds its line's place, and draws no line.
        expect(screen.queryByTestId('reports-card-ci-trend')).toBeNull()
    })

    it('opens on the months from the first that holds anything, and says since when', async () => {
        await renderPage()
        expect((await screen.findByTestId('reports-months-span')).textContent).toBe('since April 2026')
        expect(screen.getAllByTestId(/^reports-bar-/u)).toHaveLength(7)
        expect(screen.getByRole('button', { name: 'Show 7 months as a table' })).toBeTruthy()
        // No span is pressed while the page fits the journal.
        const spans = within(screen.getByRole('radiogroup', { name: 'Span' })).getAllByRole('radio')
        expect(spans.map((s) => s.getAttribute('aria-checked'))).toEqual(['false', 'false', 'false'])
    })

    it('draws every month of a span picked, the empty ones too', async () => {
        await renderPage('/reports?months=12')
        expect((await screen.findByTestId('reports-months-span')).textContent).toBe('12 months')
        expect(screen.getAllByTestId(/^reports-bar-/u)).toHaveLength(12)
    })

    it('stacks each month by kind with the sessions outside canopy on top, and marks the month picked', async () => {
        await renderPage()
        const october = await screen.findByTestId('reports-bar-2026-10')
        expect(october.dataset['marked']).toBe('true')
        expect(within(october).getByTestId('reports-segment-overseer')).toBeTruthy()
        expect(within(october).getByTestId('reports-segment-outside')).toBeTruthy()
        expect(october.getAttribute('title')).toBe(
            'October 2026: $10.00, overseer $2.00, workers $6.00, outside canopy $2.00',
        )
        expect(screen.getByTestId('reports-bar-2026-04').dataset['marked']).toBeUndefined()
    })

    it("says the month before's cost in the description", async () => {
        await renderPage()
        expect(
            await screen.findByText('$10.00 in October 2026 · 1 ticket landed · 1 PR · $3.00 in September'),
        ).toBeTruthy()
    })

    it("draws Delivery's medians across the months over its table, the latest beside each name", async () => {
        await renderPage()
        const trends = await screen.findByTestId('reports-trends')
        expect(within(trends).getByTestId('reports-trend-iterations').textContent).toContain('iterations1')
        // A point for each month with a median, which says the month, and for a time its clock, on hover.
        const toLand = within(trends).getByTestId('reports-trend-to-land-line')
        expect(within(toLand).getByTestId('reports-trend-to-land-line-point-2026-10').getAttribute('title')).toBe(
            "Oct 2026: 20.0h · From GitHub's times",
        )
        expect(within(toLand).queryByTestId('reports-trend-to-land-line-point-2026-05')).toBeNull()
        // The table stays, for a screen reader and for picking a month.
        expect(screen.getAllByTestId('reports-delivery-month')).toHaveLength(7)
    })

    it("bars each kind's and model's share of the month, and links each landed ticket's PRs", async () => {
        await renderPage()
        const kinds = await screen.findByTestId('reports-kind-table')
        expect(within(kinds).getAllByTestId('cell-bar')).toHaveLength(3)
        expect(within(screen.getByTestId('reports-model-table')).getAllByTestId('cell-bar')).toHaveLength(2)
        const [landed] = screen.getAllByTestId('reports-landed-ticket')
        expect(within(landed ?? document.body).getByRole('link', { name: 'acme/web#7' })).toBeTruthy()
    })
})
