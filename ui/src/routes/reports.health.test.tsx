import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { HealthCounts, HealthFailure, HealthReport } from '@/api/types'

import { Route } from './reports.health'

afterEach(() => {
    cleanup()
})

const NONE: HealthCounts = { overseer: 0, workers: 0, plans: 0, chores: 0, reviews: 0, tasks: 0 }

// A worker's run the harness explained, and the newest of the two it explained alike.
const WORKER: HealthFailure = {
    kind: 'workers',
    id: 40,
    what: 'implement',
    status: 'failed',
    started_at: '2026-10-08T10:45:00Z',
    ticket: 'PROJ-1',
    pr_url: null,
    chore: null,
    task_id: null,
    note: 'the worker exited 1 without a result line',
    cost_usd: 0.5,
}

// A task's run an agent's own words explained.
const TASK: HealthFailure = {
    kind: 'tasks',
    id: 2,
    what: 'task',
    status: 'failed',
    started_at: '2026-10-08T07:00:00Z',
    ticket: null,
    pr_url: null,
    chore: null,
    task_id: 2,
    note: 'CocoaPods cannot resolve the pods',
    cost_usd: 0.25,
}

// A week of ten runs, three failed: two workers' alike, and a task's; a guard stuck on one ticket; and the durations.
const REPORT: HealthReport = {
    days: 7,
    since: '2026-10-02T00:00:00Z',
    until: '2026-10-09T00:00:00Z',
    previous: {
        since: '2026-09-25T00:00:00Z',
        until: '2026-10-02T00:00:00Z',
        runs_ended: 8,
        failed: 1,
        failed_cost_usd: 0.2,
    },
    outcomes: [
        { kind: 'overseer', what: 'live', status: 'ok', failed: false, runs: 4, cost_usd: 0.8 },
        { kind: 'workers', what: 'implement', status: 'done', failed: false, runs: 2, cost_usd: 3 },
        { kind: 'workers', what: 'implement', status: 'failed', failed: true, runs: 2, cost_usd: 1 },
        { kind: 'tasks', what: 'task', status: 'failed', failed: true, runs: 1, cost_usd: 0.25 },
        { kind: 'tasks', what: 'task', status: 'stopped', failed: false, runs: 1, cost_usd: null },
    ],
    failures: [WORKER, TASK],
    causes: [
        { note: WORKER.note, runs: 2, kinds: ['workers'], latest: WORKER },
        { note: null, runs: 1, kinds: ['tasks'], latest: TASK },
    ],
    refusals: [
        {
            guard: 'running',
            decisions: 5,
            ticks: 5,
            last_tick: 9,
            asks: [{ ticket: 'PROJ-2', chore: null, pr: null, kind: 'resume', decisions: 5, last_tick: 9 }],
        },
    ],
    per_day: [
        { day: '2026-10-07', start: '2026-10-07T00:00:00Z', ended: { ...NONE, overseer: 2 }, failed: NONE },
        {
            day: '2026-10-08',
            start: '2026-10-08T00:00:00Z',
            ended: { ...NONE, overseer: 2, workers: 4, tasks: 2 },
            failed: { ...NONE, workers: 2, tasks: 1 },
        },
    ],
    durations: [
        {
            kind: 'workers',
            what: 'implement',
            runs: 4,
            median_minutes: 36,
            p90_minutes: 44,
            longest_minutes: 45,
            timeouts: 1,
            limit_minutes: 45,
            bins: { under_quarter: 0, under_half: 1, under_three_quarters: 0, under_limit: 2, over_limit: 1 },
        },
        {
            kind: 'tasks',
            what: 'task',
            runs: 2,
            median_minutes: 5,
            p90_minutes: 6,
            longest_minutes: 6,
            timeouts: 0,
            limit_minutes: null,
            bins: null,
        },
    ],
    unpriced: [],
}

/** The health page at `/reports/health`, its week's report already read as `report`. */
async function renderPage(report: HealthReport) {
    // Nothing reads the server: the report is the one set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.healthReport(report.days), report)
    const root = createRootRoute()
    const page = Route.update({ id: '/reports/health', path: '/reports/health', getParentRoute: () => root } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: ['/reports/health'] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
}

// A row's cells' text, its head first.
function cells(row: HTMLElement): string[] {
    return [...row.children].map((cell) => cell.textContent)
}

describe('the health page', () => {
    it("heads the page with the window's figures, what the failures cost among them", async () => {
        await renderPage(REPORT)
        const tiles = await screen.findByTestId('health-tiles')
        const shown = ['runs', 'failed', 'rate', 'failed-cost']
        expect(shown.map((key) => within(tiles).getByTestId(`health-${key}`).textContent)).toEqual([
            '10',
            '3',
            '30%',
            '$1.25',
        ])
        expect(within(screen.getByRole('banner')).getByRole('radiogroup', { name: 'Window' })).toBeTruthy()
    })

    it('groups how runs ended under each kind, its sorts under it with their statuses as chips', async () => {
        await renderPage(REPORT)
        const table = await screen.findByTestId('health-outcome-table')
        const workers = within(table).getByTestId('health-kind-workers')
        // The kind's row: its name, its failed share, its runs, and what they cost.
        expect(within(workers).getByRole('rowheader', { name: 'workers' })).toBeTruthy()
        expect(cells(within(workers).getAllByRole('row')[0] as HTMLElement)).toEqual(['workers', '50%', '4', '$4.00'])
        // A row per sort, the most runs first, so one line holds every way it ended.
        expect(
            within(workers)
                .getAllByTestId('health-outcome')
                .map((row) => cells(row)),
        ).toEqual([['implement', 'done2failed2', '4', '$4.00']])
        const tasks = within(table).getByTestId('health-kind-tasks')
        expect(
            within(tasks)
                .getAllByTestId('health-outcome')
                .map((row) => cells(row)),
        ).toEqual([['task', 'failed1stopped1', '2', '$0.25']])
    })

    it('gives each day of the folded table its failure rate', async () => {
        await renderPage(REPORT)
        expect(await screen.findByRole('button', { name: 'Show 2 days as a table' })).toBeTruthy()
        expect(cells(screen.getByTestId('health-day-2026-10-08')).slice(-3)).toEqual(['3', '8', '38%'])
        expect(cells(screen.getByTestId('health-day-2026-10-07')).slice(-3)).toEqual(['0', '2', '0%'])
    })

    it('counts the failures by cause, the newest of each to open, and the rest as other', async () => {
        await renderPage(REPORT)
        const rows = within(await screen.findByTestId('health-cause-table')).getAllByTestId('health-cause')
        expect(rows.map((row) => cells(row).slice(0, 4))).toEqual([
            ['the worker exited 1 without a result line', '2', 'workers', 'run:40'],
            ['other', '1', 'tasks', 'task:2#2'],
        ])
        expect(within(rows[0] as HTMLElement).getByRole('link', { name: 'run:40' })).toBeTruthy()
    })

    it('says under each guard what it refused, so one ticket refused tick after tick shows', async () => {
        await renderPage(REPORT)
        const guard = await screen.findByTestId('health-refusal')
        expect(within(guard).getByRole('rowheader', { name: 'running' })).toBeTruthy()
        const [ask] = within(guard).getAllByTestId('health-ask')
        expect(cells(ask as HTMLElement)).toEqual(['PROJ-2', 'resume', '5', 'tick:9'])
        expect(within(ask as HTMLElement).getByRole('link', { name: 'PROJ-2' })).toBeTruthy()
    })

    it('times each sort against its timeout, its spread in words for a screen reader', async () => {
        await renderPage(REPORT)
        const rows = within(await screen.findByTestId('health-duration-table')).getAllByTestId('health-duration')
        expect(rows.map((row) => cells(row))).toEqual([
            ['implement', '4', '36m', '44m', '45m', '45m', '1', '1 at 25–50%, 2 at 75–100%, 1 at the limit'],
            ['task', '2', '5.0m', '6.0m', '6.0m', '–', '0', 'no timeout'],
        ])
        expect(screen.getByTestId('health-spread-legend').textContent).toContain('at the limit')
    })

    it('says so when nothing failed and no guard refused', async () => {
        await renderPage({ ...REPORT, failures: [], causes: [], refusals: [], durations: [] })
        expect((await screen.findByTestId('health-causes')).textContent).toContain('no run failed in these 7 days')
        expect(screen.getByTestId('health-refusals').textContent).toContain('no guard refused anything')
        expect(screen.getByTestId('health-durations').textContent).toContain('no run ended in these 7 days')
    })
})
