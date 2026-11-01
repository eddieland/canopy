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
    heads: 4,
    green_first: 3,
    checks: [
        { name: 'e2e', runs: 5, red: 2, green: 3, followed: 2, passed: 1, reruns: 1, reruns_green: 1 },
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
    pull_requests: [],
    median_hours_to_green: null,
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
        ).toEqual(['PR heads', 'green first time', 'red runs', 'fix-CI resumes'])
        expect(
            within(tiles)
                .getAllByRole('definition')
                .map((d) => d.textContent),
        ).toEqual(['4', '75%', '2', '1'])
        const header = screen.getByRole('banner')
        expect(within(header).getByRole('radiogroup', { name: 'Window' })).toBeTruthy()
    })

    it('folds the red checks by day into a table a screen reader reads, opened from its row count', async () => {
        await renderPage(REPORT)
        expect(await screen.findByRole('button', { name: 'Show 2 days as a table' })).toBeTruthy()
        expect(screen.getAllByTestId(/^ci-day-/u)).toHaveLength(2)
    })

    it('lists the checks the worst first, and says what counts as red and what it cannot see', async () => {
        await renderPage(REPORT)
        const rows = within(await screen.findByTestId('ci-check-table')).getAllByTestId('ci-check')
        expect(rows.map((row) => [...row.children].map((cell) => cell.textContent))).toEqual([
            ['e2e', '5', '2', '40%', '1 of 2'],
            ['lint', '4', '0', '0%', '–'],
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
            'kicks are off: trust.max_flaky_kicks is 0',
        )
    })

    it("counts the cooldown's refusals, and leaves the rest to Health", async () => {
        await renderPage(REPORT)
        const line = await screen.findByTestId('ci-cooldown-line')
        expect(line.textContent).toContain('The cooldown held 3 resumes in 2 ticks')
        expect(within(line).getByRole('link', { name: 'Health' }).getAttribute('href')).toBe('/reports/health')
        expect(within(line).getByRole('link', { name: 'tick:9' })).toBeTruthy()
    })

    it('says so when nothing was observed', async () => {
        await renderPage({ ...REPORT, heads: 0, green_first: 0, checks: [], series: [], per_day: [], fixes: [] })
        expect(await screen.findByText('no PR head checked · 1 flaky kick over 7 days')).toBeTruthy()
        expect(screen.getByText('no check run was observed in these 7 days')).toBeTruthy()
        expect(screen.getByText('no resume for CI started in these 7 days')).toBeTruthy()
    })
})
