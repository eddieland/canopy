import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { CiReport } from '@/api/types'

import { Route } from './reports.ci'

afterEach(() => {
    cleanup()
})

const PR = 'https://github.com/acme/web/pull/7'

// A week with a check red twice, one fixed by its next head, a fix, a kick that came back red, and the cooldown.
const REPORT: CiReport = {
    days: 7,
    since: '2026-10-02T00:00:00Z',
    until: '2026-10-09T00:00:00Z',
    previous: {
        since: '2026-09-25T00:00:00Z',
        until: '2026-10-02T00:00:00Z',
        heads: 5,
        green_first: 3,
        red: 4,
        fixes: 1,
        fixes_green: 1,
    },
    heads: 4,
    green_first: 3,
    checks: [
        { name: 'e2e', runs: 5, red: 2, green: 3, followed: 2, passed: 1, reruns: 3, reruns_green: 2 },
        { name: 'lint', runs: 4, red: 0, green: 3, followed: 0, passed: 0, reruns: 0, reruns_green: 0 },
    ],
    series: ['e2e'],
    per_day: [
        { day: '2026-10-07', start: '2026-10-07T00:00:00Z', red: [1], heads: 2, green_first: 1 },
        { day: '2026-10-08', start: '2026-10-08T00:00:00Z', red: [1], heads: 2, green_first: 2 },
    ],
    fixes: [
        {
            run_id: 12,
            ticket_key: 'PROJ-1',
            kind: 'resume',
            status: 'done',
            started_at: '2026-10-08T10:00:00Z',
            cost_usd: 0.4,
            checks: [{ pr_url: PR, name: 'e2e', next: 'green' }],
            hours_to_green: 4,
        },
    ],
    kicks: [
        {
            run_id: 13,
            repo: 'web',
            branch: 'agent/PROJ-1',
            pr_url: PR,
            kicked_at: '2026-10-08T11:00:00Z',
            kick: 1,
            red_before: ['e2e'],
            still_red: ['e2e'],
            checked: true,
        },
    ],
    kicked_pull_requests: [{ url: PR, ticket_key: 'PROJ-1', phase: 'ci_red', kicks: 1, most: 1, still_red: 1 }],
    pull_requests: [
        {
            url: PR,
            ticket_key: 'PROJ-1',
            phase: 'ci_red',
            red_at: '2026-10-08T09:00:00Z',
            green_at: null,
            hours_to_green: null,
        },
        {
            url: 'https://github.com/acme/web/pull/8',
            ticket_key: 'PROJ-2',
            phase: null,
            red_at: '2026-10-07T09:00:00Z',
            green_at: '2026-10-07T13:00:00Z',
            hours_to_green: 4,
        },
    ],
    median_hours_to_green: 4,
    max_flaky_kicks: 2,
    cooldown: { guard: 'cooldown', decisions: 3, ticks: 2, last_tick: 9, asks: [] },
}

/** The CI page at `/reports/ci`, its week's report already read as `report`. */
async function renderPage(report: CiReport) {
    // Nothing reads the server: the report is the one set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.ciReport(report.days), report)
    const root = createRootRoute()
    const page = Route.update({ id: '/reports/ci', path: '/reports/ci', getParentRoute: () => root } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: ['/reports/ci'] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
}

describe('the CI page', () => {
    it("says the window's state under its title", async () => {
        await renderPage(REPORT)
        expect(await screen.findByText('75% of PR heads green first time · 1 flaky kick over 7 days')).toBeTruthy()
    })

    it("heads the page with the window's figures, its window in the header beside the title", async () => {
        await renderPage(REPORT)
        const tiles = await screen.findByTestId('ci-tiles')
        expect(
            within(tiles)
                .getAllByRole('term')
                .map((t) => t.textContent),
        ).toEqual(['PR heads', 'green first time', 'red runs', 'fix-CI resumes', 'went green', 'time to green'])
        const shown = ['heads', 'green-first', 'red', 'fixes', 'fixes-green', 'red-spell']
        expect(shown.map((key) => within(tiles).getByTestId(`ci-${key}`).textContent)).toEqual([
            '4',
            '75%',
            '2',
            '1',
            '1',
            '4.0h',
        ])
        // Each against the week before's: 5 heads, 3 of them green first, 4 red runs, and a fix that went green. The
        // time to green has no week before's.
        expect(shown.slice(0, 5).map((key) => within(tiles).getByTestId(`ci-${key}-delta`).textContent)).toEqual([
            '−1 on the 7 days before',
            '+15 pts on the 7 days before',
            '−2 on the 7 days before',
            'same as the 7 days before',
            'same as the 7 days before',
        ])
        expect(within(tiles).queryByTestId('ci-red-spell-delta')).toBeNull()
        const header = screen.getByRole('banner')
        expect(within(header).getByRole('radiogroup', { name: 'Window' })).toBeTruthy()
    })

    it('folds the red checks by day into a table a screen reader reads, opened from its row count', async () => {
        await renderPage(REPORT)
        expect(await screen.findAllByRole('button', { name: 'Show 2 days as a table' })).toHaveLength(2)
        expect(screen.getAllByTestId(/^ci-day-/u)).toHaveLength(2)
    })

    it('says each day how many heads went green first time, the newest first', async () => {
        await renderPage(REPORT)
        const rows = within(await screen.findByTestId('ci-green-first-table')).getAllByTestId(/^ci-green-day-/u)
        expect(rows.map((row) => [...row.children].map((cell) => cell.textContent))).toEqual([
            ['Oct 8', '2', '2', '100%'],
            ['Oct 7', '2', '1', '50%'],
        ])
    })

    it('times each PR from red to green, a still-red one first, with its caveat', async () => {
        await renderPage(REPORT)
        expect((await screen.findByTestId('ci-to-green-median')).textContent).toBe('median 4.0h')
        const rows = within(screen.getByTestId('ci-to-green-pull-request-table')).getAllByTestId(
            'ci-to-green-pull-request',
        )
        expect(rows.map((row) => row.lastElementChild?.textContent)).toEqual(['still red', '4.0h'])
        expect(screen.getByTestId('ci-to-green-caveat').textContent).toContain('not when it did')
        // A fix whose check went green on the next head says how long its PR took.
        expect(within(screen.getByTestId('ci-fix-12')).getByText('4.0h')).toBeTruthy()
    })

    it('lists the checks the worst first, and says what counts as red and what it cannot see', async () => {
        await renderPage(REPORT)
        const rows = within(await screen.findByTestId('ci-check-table')).getAllByTestId('ci-check')
        // The rate first, then red and runs beside it, then the next head and the same head's reruns.
        expect(rows.map((row) => [...row.children].map((cell) => cell.textContent))).toEqual([
            ['e2e', '40%', '2', '5', '1 of 2', '2 of 3flaky'],
            ['lint', '0%', '0', '4', '–', '–'],
        ])
        expect(screen.getByTestId('ci-limits').textContent).toContain('A commit status has no check run')
        expect(screen.getByTestId('ci-limits').textContent).toContain('cancelled, skipped, neutral, stale')
    })

    it("sums the fixes' red-to-green rate and says each check's next head", async () => {
        await renderPage(REPORT)
        expect((await screen.findByTestId('ci-fix-rate')).textContent).toBe('1 of 1 check green on the next head')
        const fixed = within(screen.getByTestId('ci-fix-12')).getByTestId('ci-fixed')
        expect(fixed.textContent).toContain('e2e')
        expect(fixed.textContent).toContain('green')
        expect(within(screen.getByTestId('ci-fix-12')).getByRole('link', { name: 'run:12' })).toBeTruthy()
    })

    it('holds the kicks against the limit, and names the ones that came back red', async () => {
        await renderPage(REPORT)
        expect((await screen.findByTestId('ci-kick-limit')).textContent).toBe('trust.max_flaky_kicks = 2')
        const [row] = within(screen.getByTestId('ci-kicked-pull-request-table')).getAllByTestId(
            'ci-kicked-pull-request',
        )
        expect([...(row?.children ?? [])].slice(1).map((cell) => cell.textContent)).toEqual([
            'PROJ-1',
            '1',
            '1 of 2',
            '1',
        ])
        expect(within(screen.getByTestId('ci-red-kicks')).getByTestId('ci-red-kick').textContent).toContain(
            'kick 1 of 2',
        )
    })

    it('says kicks are off when the limit is 0 and none were made', async () => {
        await renderPage({ ...REPORT, kicks: [], kicked_pull_requests: [], max_flaky_kicks: 0 })
        expect((await screen.findByTestId('ci-kicks')).textContent).toContain(
            'Kicks are off: trust.max_flaky_kicks is 0',
        )
        // One panel holds the reruns: the kicks' line, and the cooldown under it.
        expect(within(screen.getByTestId('ci-reruns')).getByTestId('ci-cooldown-line')).toBeTruthy()
    })

    it("counts the cooldown's refusals, and leaves the rest to Health", async () => {
        await renderPage(REPORT)
        const line = await screen.findByTestId('ci-cooldown-line')
        expect(line.textContent).toContain('The cooldown held 3 resumes in 2 ticks')
        expect(within(line).getByRole('link', { name: 'Health' }).getAttribute('href')).toBe('/reports/health')
        expect(within(line).getByRole('link', { name: 'tick:9' })).toBeTruthy()
    })

    it('says so when nothing was observed', async () => {
        await renderPage({
            ...REPORT,
            heads: 0,
            green_first: 0,
            checks: [],
            series: [],
            per_day: [],
            fixes: [],
            pull_requests: [],
        })
        expect(await screen.findByText('no PR head checked · 1 flaky kick over 7 days')).toBeTruthy()
        expect(screen.getByText('no PR head was checked in these 7 days')).toBeTruthy()
        expect(screen.getByText('no PR had a check run in these 7 days')).toBeTruthy()
        expect(screen.getByText('no check run was observed in these 7 days')).toBeTruthy()
        expect(screen.getByText('no resume for CI started in these 7 days')).toBeTruthy()
    })
})
