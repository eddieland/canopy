import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { SpendBreakdown, SpendCosts, SpendDay } from '@/api/types'

import { Route } from './reports.spend'

afterEach(() => {
    cleanup()
})

const NONE: SpendCosts = {
    overseer: null,
    idle: null,
    dry_run: null,
    workers: null,
    plans: null,
    chores: null,
    reviews: null,
    tasks: null,
    outside: null,
    total: null,
}

// A day of October 2026 that cost what `costs` says.
function day(date: number, costs: Partial<SpendCosts>): SpendDay {
    const name = `2026-10-${String(date).padStart(2, '0')}`
    return { day: name, start: `${name}T00:00:00Z`, costs: { ...NONE, ...costs }, done: 0 }
}

// A week to October 8th, a quarter through a month with a $40 budget it is headed over: the overseer, its idle ticks,
// and the workers spent; no dry run, no task, and the loop has never read the sessions outside canopy.
const SPENT: SpendCosts = { ...NONE, overseer: 0.6, idle: 0.3, workers: 2, plans: 1, chores: 0.5, reviews: 0.4 }
const WEEK: SpendBreakdown = {
    since: '2026-10-02T00:00:00Z',
    days: 7,
    hours: null,
    per_day: [2, 3, 4, 5, 6, 7, 8].map((d) => day(d, d === 8 ? { ...SPENT, total: 4.5 } : {})),
    totals: { ...SPENT, total: 4.5 },
    ticks: [
        { group: 'idle', ticks: 3, cost_usd: 0.3, without_overseer: 1 },
        { group: 'busy', ticks: 2, cost_usd: 0.3, without_overseer: 0 },
        { group: 'hand_run', ticks: 0, cost_usd: null, without_overseer: 0 },
        { group: 'not_ok', ticks: 0, cost_usd: null, without_overseer: 0 },
        { group: 'dry_run', ticks: 0, cost_usd: null, without_overseer: 0 },
    ],
    woken: [{ by: 'timer', ticks: 5, cost_usd: 0.6, without_overseer: 1 }],
    unpriced: [{ kind: 'workers', runs: 3, unpriced: 1 }],
    idle_share: 0.5,
    idle_ticks: [],
    done: 1,
    per_done: 4.5,
    tickets: [],
    pull_requests: [
        {
            url: 'https://github.com/acme/web/pull/7',
            ticket_key: 'PROJ-1',
            phase: null,
            runs: 2,
            reviews: 1,
            cost_usd: 3,
        },
        {
            url: 'https://github.com/acme/web/pull/8',
            ticket_key: 'PROJ-2',
            phase: null,
            runs: 1,
            reviews: 0,
            cost_usd: 1,
        },
    ],
    tools: [],
    models: [],
    month: {
        month: '2026-10',
        since: '2026-10-01T00:00:00Z',
        until: '2026-11-01T00:00:00Z',
        budget_usd: 40,
        spent_usd: 15.76,
        elapsed: 0.25,
        projected_usd: 65.14,
        alerts: [50, 80, 100],
        runs_usd: 15.76,
        outside_usd: 0,
        sessions_read_at: null,
    },
    sessions: null,
    first_call_weeks: [],
    previous: {
        since: '2026-09-25T00:00:00Z',
        until: '2026-10-02T00:00:00Z',
        totals: { ...NONE, overseer: 0.4, workers: 3, total: 3.4 },
        done: 2,
        per_done: 1.7,
    },
}

// The 30 days to October 8th, every day's workers a dollar.
const MONTH: SpendBreakdown = {
    ...WEEK,
    since: '2026-09-09T00:00:00Z',
    days: 30,
    per_day: Array.from({ length: 30 }, (_, i) => {
        const start = new Date(Date.UTC(2026, 8, 9 + i))
        const name = start.toISOString().slice(0, 10)
        return { day: name, start: start.toISOString(), costs: { ...NONE, workers: 1, total: 1 }, done: 0 }
    }),
}

/** The spend page at `path`, its window's breakdown already read as `found`. */
async function renderPage(found: SpendBreakdown, path = '/reports/spend') {
    // Nothing reads the server: the breakdown is the one set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.spendBreakdown(found.days === 30 ? { days: 30 } : { days: 7 }), found)
    const root = createRootRoute()
    const page = Route.update({ id: '/reports/spend', path: '/reports/spend', getParentRoute: () => root } as never)
    // Where the page's links go, so the router can build them.
    const ticks = createRoute({ getParentRoute: () => root, path: '/workspace/ticks' })
    const router = createRouter({
        routeTree: root.addChildren([page, ticks]),
        history: createMemoryHistory({ initialEntries: [path] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
}

describe('the spend page', () => {
    it("labels the budget's bar with the day and each alert short of it, under one line of pace", async () => {
        await renderPage(WEEK)
        expect((await screen.findByTestId('spend-budget-text')).textContent).toBe('Headed over: $15.76 of $40 (39%)')
        expect(screen.getByTestId('spend-budget-day').textContent).toBe('day 8 of 31')
        expect(screen.getByTestId('spend-budget-alert-50').textContent).toBe('50%')
        expect(screen.getByTestId('spend-budget-alert-80').textContent).toBe('80%')
        expect(screen.queryByTestId('spend-budget-alert-100')).toBeNull()
        expect(screen.getByTestId('spend-budget-pace').textContent).toBe('On pace to spend $65.14 of $40.')
        // The bar is the eye's: a screen reader hears the day and the alerts in a sentence.
        expect(screen.getByTestId('spend-budget-alerts').textContent).toBe(
            'It is day 8 of 31 of the month. A sink that takes loop events hears at 50%, 80%, and 100%.',
        )
    })

    it('folds the totals at a dash into a line under the rest, each against the week before', async () => {
        await renderPage(WEEK)
        const tiles = await screen.findByTestId('spend-total-tiles')
        expect(
            within(tiles)
                .getAllByRole('term')
                .map((t) => t.textContent),
        ).toEqual(['total', 'overseer', 'idle ticks', 'workers', 'plans', 'chores', 'reviews'])
        expect(screen.getByTestId('spend-total-folded').textContent).toBe(
            'No tasks, no dry runs, sessions outside canopy not read yet.',
        )
        expect(screen.getByTestId('spend-total-total-delta').textContent).toBe('+$1.10')
        expect(screen.getByTestId('spend-done-delta').textContent).toBe('−1')
        expect(screen.getByTestId('spend-unpriced').textContent).toBe('No cost reported: 1 of 3 worker runs.')
    })

    it("draws a bar of each PR's share of the dearest one's beside what it spent", async () => {
        await renderPage(WEEK)
        const table = await screen.findByTestId('spend-pull-request-table')
        expect(within(table).getAllByTestId('cell-bar')).toHaveLength(2)
    })

    it("sets the ticks' tables side by side, idle ticks' share the readout, the idle ones linked", async () => {
        await renderPage(WEEK)
        const panel = await screen.findByTestId('spend-ticks')
        expect(within(panel).getByText('Ticks')).toBeTruthy()
        expect(within(panel).getByTestId('spend-idle-share').textContent).toBe('50% idle')
        expect(within(panel).getByRole('columnheader', { name: 'bought' })).toBeTruthy()
        expect(within(panel).getByRole('columnheader', { name: 'woken by' })).toBeTruthy()
        expect(within(panel).getByTestId('spend-groups-idle').textContent).toContain('3')
        expect(within(panel).getByTestId('spend-woken-table-timer').textContent).toContain('5')
        expect(within(panel).getByRole('link', { name: 'Open the idle ticks' }).getAttribute('href')).toBe(
            '/workspace/ticks?idle=true',
        )
    })

    it('offers By day by week over 30 days alone, and draws and tables the weeks when picked', async () => {
        await renderPage(WEEK)
        await screen.findByTestId('spend-by-day')
        expect(screen.queryByRole('radiogroup', { name: 'Pitch' })).toBeNull()
        cleanup()

        await renderPage(MONTH, '/reports/spend?days=30&pitch=week')
        const panel = await screen.findByTestId('spend-by-day')
        expect(within(panel).getByText('By week')).toBeTruthy()
        expect(within(panel).getByRole('radiogroup', { name: 'Pitch' })).toBeTruthy()
        // September 9th, a Wednesday, to October 8th, a Thursday: five weeks, part ones at both ends.
        expect(within(panel).getAllByTestId(/^spend-bar-/u)).toHaveLength(5)
        expect(within(panel).getByRole('button', { name: 'Show 5 weeks as a table' })).toBeTruthy()
        expect(within(panel).getByTestId('spend-week-2026-09-07').textContent).toContain('week of Sep 7')
    })
})
