import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { ConnectorsReport } from '@/api/types'

import { Route } from './reports.connectors'

afterEach(() => {
    cleanup()
})

// A week of two sources: the tracker's latest run stale, the reader's fresh; a tick's partial and a poll that failed.
const REPORT: ConnectorsReport = {
    days: 7,
    since: '2026-10-02T00:00:00Z',
    until: '2026-10-09T00:00:00Z',
    max_age_minutes: 30,
    journal_days: 90,
    sources: [
        {
            name: 'jira',
            kind: 'tracker',
            run_id: 40,
            tick_id: 9,
            status: 'partial',
            ended_at: '2026-10-08T11:30:00Z',
            missed: 'did not read 1 ticket (ABC-1) whole',
            oldest_at: null,
            never: 2,
            stale: true,
            through: null,
        },
        {
            name: 'github',
            kind: 'vcs',
            run_id: 41,
            tick_id: null,
            status: 'ok',
            ended_at: '2026-10-08T11:31:00Z',
            missed: null,
            oldest_at: '2026-10-08T11:20:00Z',
            never: 0,
            stale: false,
            through: null,
        },
        {
            name: 'store',
            kind: 'artifacts',
            run_id: null,
            tick_id: null,
            status: null,
            ended_at: null,
            missed: null,
            oldest_at: null,
            never: 1,
            stale: true,
            through: 0,
        },
    ],
    runs: [
        {
            source: 'jira',
            kind: 'tracker',
            runs: 20,
            ticks: 4,
            polls: 16,
            ok: 19,
            partial: 1,
            failed: 0,
            median_minutes: 0.25,
            p90_minutes: 0.5,
            longest_minutes: 0.6,
            limit_minutes: 2,
            recorded: { ticket: 120, comment: 7 },
            refused: { comment: 1 },
        },
        {
            source: 'github',
            kind: 'vcs',
            runs: 20,
            ticks: 4,
            polls: 16,
            ok: 19,
            partial: 0,
            failed: 1,
            median_minutes: 1.6,
            p90_minutes: 1.9,
            longest_minutes: 2,
            limit_minutes: 2,
            recorded: { pr: 40 },
            refused: {},
        },
    ],
    per_day: [
        { day: '2026-10-07', start: '2026-10-07T00:00:00Z', short: [0, 1] },
        { day: '2026-10-08', start: '2026-10-08T00:00:00Z', short: [1, 0] },
    ],
    newest: [
        {
            id: 40,
            source: 'jira',
            kind: 'tracker',
            tick_id: 9,
            started_at: '2026-10-08T11:29:45Z',
            minutes: 0.25,
            status: 'partial',
            missed: 'did not read 1 ticket (ABC-1) whole',
            stderr: '<b>ABC-1</b>: the tracker answered 503',
        },
        {
            id: 22,
            source: 'github',
            kind: 'vcs',
            tick_id: null,
            started_at: '2026-10-07T03:00:00Z',
            minutes: 2,
            status: 'failed',
            missed: 'it did not finish in 2 minutes: timed out',
            stderr: 'timed out',
        },
    ],
    refusals: [{ source: 'jira', line: 'comment', lines: 1, runs: 1, last_at: '2026-10-08T11:29:45Z' }],
    previous: { since: '2026-09-25T00:00:00Z', until: '2026-10-02T00:00:00Z', runs: 40, short: 4, refused: 0 },
}

/** The Connectors page at `/reports/connectors`, its week's report already read as `report`. */
async function renderPage(report: ConnectorsReport) {
    // Nothing reads the server: the report is the one set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.connectorsReport(report.days), report)
    const root = createRootRoute()
    const page = Route.update({
        id: '/reports/connectors',
        path: '/reports/connectors',
        getParentRoute: () => root,
    } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: ['/reports/connectors'] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
}

describe('the Connectors page', () => {
    it("says the window's state under its title, each stale source by name", async () => {
        await renderPage(REPORT)
        expect(
            await screen.findByText('2 of 40 runs read less than asked over 7 days · jira stale · store stale'),
        ).toBeTruthy()
    })

    it("heads the page with the window's figures against the week before's, its window beside the title", async () => {
        await renderPage(REPORT)
        const tiles = await screen.findByTestId('connectors-tiles')
        expect(
            within(tiles)
                .getAllByRole('term')
                .map((t) => t.textContent),
        ).toEqual(['runs', 'read less than asked', 'short rate', 'refused lines'])
        const shown = ['runs', 'short', 'rate', 'refused']
        expect(shown.map((key) => within(tiles).getByTestId(`connectors-${key}`).textContent)).toEqual([
            '40',
            '2',
            '5%',
            '1',
        ])
        expect(shown.map((key) => within(tiles).getByTestId(`connectors-${key}-delta`).textContent)).toEqual([
            'same as the 7 days before',
            '−2 on the 7 days before',
            '−5 pts on the 7 days before',
            '+1 on the 7 days before',
        ])
        const header = screen.getByRole('banner')
        expect(within(header).getByRole('radiogroup', { name: 'Window' })).toBeTruthy()
    })

    it('names each source now: its latest run, the tick that made it or a poll, and its freshness', async () => {
        await renderPage(REPORT)
        expect((await screen.findByTestId('connectors-max-age')).textContent).toBe('connect.max_age_minutes = 30')
        const jira = screen.getByTestId('connectors-source-jira')
        expect(within(jira).getByText('partial')).toBeTruthy()
        expect(within(jira).getByRole('link', { name: 'tick:9' })).toBeTruthy()
        expect(within(jira).getByText('stale')).toBeTruthy()
        expect(within(jira).getByText('2 never observed')).toBeTruthy()
        const github = screen.getByTestId('connectors-source-github')
        expect(within(github).getByText('poll')).toBeTruthy()
        expect(within(github).queryByText('stale')).toBeNull()
        const store = screen.getByTestId('connectors-source-store')
        expect(within(store).getByText('never ran')).toBeTruthy()
        expect(within(store).getByText('feed through change 0, never read to its end')).toBeTruthy()
    })

    it("counts each source's runs by how they ended, against its timeout, with the lines it read", async () => {
        await renderPage(REPORT)
        const rows = within(await screen.findByTestId('connectors-run-table')).getAllByTestId(/^connectors-runs-/u)
        // The bar's cell sits beside the share's, empty for a screen reader.
        expect(rows.map((row) => [...row.children].map((cell) => cell.textContent))).toEqual([
            [
                'jira',
                '20',
                '4',
                '16',
                '19',
                '1',
                '0',
                '5%',
                '',
                '15s',
                '30s',
                '2.0m',
                '120 ticket, 7 comment',
                '1 comment',
            ],
            ['github', '20', '4', '16', '19', '0', '1', '5%', '', '1.6m', '1.9m', '2.0m', '40 pr', '–'],
        ])
        const limits = screen.getByTestId('connectors-limits').textContent
        expect(limits).toContain('a source that reads everything and finds nothing new is ok')
        expect(limits).toContain('a poll between ticks raises nothing')
        expect(limits).toContain('The journal keeps a run 90 days (retention.journal_days)')
    })

    it('folds the runs that read less than asked by day into a table a screen reader reads', async () => {
        await renderPage(REPORT)
        expect(await screen.findByRole('button', { name: 'Show 2 days as a table' })).toBeTruthy()
        const rows = within(screen.getByTestId('connectors-table')).getAllByTestId(/^connectors-day-/u)
        expect(rows.map((row) => [...row.children].map((cell) => cell.textContent))).toEqual([
            ['Oct 8', '1', '0', '1'],
            ['Oct 7', '0', '1', '1'],
        ])
    })

    it('lists the newest short runs with what they missed, a stderr as text, and their tick or a poll', async () => {
        await renderPage(REPORT)
        const partial = await screen.findByTestId('connectors-run-40')
        expect(within(partial).getByRole('link', { name: 'tick:9' })).toBeTruthy()
        expect(within(partial).getByText('did not read 1 ticket (ABC-1) whole')).toBeTruthy()
        // The connector's own words stay text: its markup is characters, never an element.
        expect(within(partial).getByText('<b>ABC-1</b>: the tracker answered 503')).toBeTruthy()
        const failed = screen.getByTestId('connectors-run-22')
        expect(within(failed).getByText('poll')).toBeTruthy()
        // A stderr the harness's words already quote is not said twice.
        expect(within(failed).getAllByText(/timed out/u)).toHaveLength(1)
    })

    it('counts the refused lines by source and kind', async () => {
        await renderPage(REPORT)
        const [row] = within(await screen.findByTestId('connectors-refusal-table')).getAllByTestId('connectors-refusal')
        expect([...(row?.children ?? [])].slice(0, 4).map((cell) => cell.textContent)).toEqual([
            'jira',
            'comment',
            '1',
            '1',
        ])
    })

    it('says so when nothing ran', async () => {
        await renderPage({
            ...REPORT,
            sources: [],
            runs: [],
            per_day: [{ day: '2026-10-08', start: '2026-10-08T00:00:00Z', short: [] }],
            newest: [],
            refusals: [],
        })
        expect(await screen.findByText('no source ran over 7 days')).toBeTruthy()
        expect(screen.getByText('no source reads')).toBeTruthy()
        expect(screen.getByText('no source ran in these 7 days')).toBeTruthy()
        expect(screen.getAllByText('every run read everything it was asked in these 7 days')).toHaveLength(2)
        expect(screen.getByText('canopy refused no line in these 7 days')).toBeTruthy()
    })
})
