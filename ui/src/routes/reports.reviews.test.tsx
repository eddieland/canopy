import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { ReviewsReport } from '@/api/types'

import { Route } from './reports.reviews'

afterEach(() => {
    cleanup()
})

const PR = 'https://github.com/acme/web/pull/7'

// A week: a PR timed on GitHub's clock and reviewed in three hours, one without its times, a trusted reviewer, two
// feedback plans, and canopy's reviewer's runs, a dismissal, and a draft.
const REPORT: ReviewsReport = {
    days: 7,
    since: '2026-10-02T00:00:00Z',
    until: '2026-10-09T00:00:00Z',
    previous: {
        since: '2026-09-25T00:00:00Z',
        until: '2026-10-02T00:00:00Z',
        reviews: 6,
        pull_requests: 1,
        first_reviews: 1,
        median_first_review_hours: 1.5,
        rounds: 2,
    },
    reviews: 4,
    first_reviews: 1,
    median_first_review_hours: 3,
    untimed: 1,
    waiting: 0,
    turnarounds: 0,
    median_turnaround_hours: null,
    median_turnaround: null,
    per_day: [
        { day: '2026-10-07', start: '2026-10-07T00:00:00Z', first_reviews: [0, 1, 0, 0], median_wait_hours: 3 },
        { day: '2026-10-08', start: '2026-10-08T00:00:00Z', first_reviews: [0, 0, 0, 0], median_wait_hours: null },
    ],
    reviewers: [
        {
            author: 'dana',
            trusted: true,
            reviews: 2,
            changes_requested: 1,
            approved: 1,
            comments: 0,
            pull_requests: 1,
            median_wait_hours: 3,
        },
        {
            author: 'carol',
            trusted: false,
            reviews: 1,
            changes_requested: 0,
            approved: 0,
            comments: 2,
            pull_requests: 1,
            median_wait_hours: null,
        },
    ],
    pull_requests: [
        {
            url: PR,
            ticket_key: 'PROJ-1',
            phase: 'review_pending',
            waiting_since: '2026-10-07T09:00:00Z',
            first_review_at: '2026-10-07T12:00:00Z',
            first_review_hours: 3,
            reviews: 3,
            changes_requested: 1,
            comments: 1,
            rounds: 2,
            cost_usd: 2.5,
            ready_at: '2026-10-07T08:00:00Z',
            merged_at: null,
            hours_to_merge: null,
            approved: 1,
            approved_at: '2026-10-08T15:00:00Z',
            rounds_to_approval: 1,
        },
    ],
    rounds: [
        {
            plan_id: 2,
            ticket_key: 'PROJ-1',
            run_id: 21,
            created_at: '2026-10-08T09:00:00Z',
            status: 'approved',
            approved_channel: 'web',
            effort: 'medium',
            pull_requests: [PR],
            plan_cost_usd: null,
            resumes: 0,
            resume_cost_usd: null,
            review_at: '2026-10-08T07:00:00Z',
            approved_at: '2026-10-08T10:00:00Z',
            resume_started_at: null,
            resume_ended_at: null,
            answered_at: null,
            turnaround_hours: null,
            turnaround: null,
        },
        {
            plan_id: 1,
            ticket_key: 'PROJ-1',
            run_id: 20,
            created_at: '2026-10-07T13:00:00Z',
            status: 'superseded',
            approved_channel: 'planner',
            effort: 'small',
            pull_requests: [PR],
            plan_cost_usd: 0.5,
            resumes: 2,
            resume_cost_usd: 2,
            review_at: null,
            approved_at: '2026-10-07T13:00:00Z',
            resume_started_at: '2026-10-07T14:00:00Z',
            resume_ended_at: '2026-10-07T15:00:00Z',
            answered_at: null,
            turnaround_hours: null,
            turnaround: null,
        },
    ],
    efforts: [
        { effort: 'small', plans: 1, resumes: 2, resume_cost_usd: 2 },
        { effort: 'medium', plans: 1, resumes: 0, resume_cost_usd: null },
    ],
    review_runs: [
        { purpose: 'own', status: 'done', runs: 2, cost_usd: 0.5 },
        { purpose: 'request', status: 'failed', runs: 1, cost_usd: null },
    ],
    dismissals: [{ reason: 'wrong', findings: 1 }],
    drafts: [{ status: 'published', drafts: 1 }],
    canopy_trusted: true,
}

/** The Reviews page at `/reports/reviews`, its week's report already read as `report`. */
async function renderPage(report: ReviewsReport) {
    // Nothing reads the server: the report is the one set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.reviewsReport(report.days), report)
    const root = createRootRoute()
    const page = Route.update({ id: '/reports/reviews', path: '/reports/reviews', getParentRoute: () => root } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: ['/reports/reviews'] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
}

/** The widths of a row's in-cell bars, in its columns' order. */
function bars(row: HTMLElement | undefined): string[] {
    return within(row ?? document.body)
        .getAllByTestId('cell-bar')
        .map((bar) => (bar.firstElementChild as HTMLElement).style.width)
}

describe('the Reviews page', () => {
    it("heads the page with the window's figures, each against the week before's", async () => {
        await renderPage(REPORT)
        const tiles = await screen.findByTestId('reviews-tiles')
        const tileKeys = ['reviews', 'prs', 'first-reviews', 'median-wait', 'rounds']
        expect(tileKeys.map((key) => within(tiles).getByTestId(`reviews-${key}`).textContent)).toEqual([
            '4',
            '1',
            '1',
            '3.0h',
            '2',
        ])
        expect(tileKeys.map((key) => within(tiles).getByTestId(`reviews-${key}-delta`).textContent)).toEqual([
            '−2 on the 7 days before',
            'same as the 7 days before',
            'same as the 7 days before',
            '+1.5h on the 7 days before',
            'same as the 7 days before',
        ])
    })

    it("says the window's state under its title, and what the median leaves out in its tile's tip", async () => {
        await renderPage(REPORT)
        expect(await screen.findByText('4 reviews on 1 PR · median first review 3.0h over 7 days')).toBeTruthy()
        // The first panel holds the chart alone: no sentence over it, and no footnote under it.
        const waits = screen.getByTestId('reviews-waits')
        expect(waits.textContent).not.toContain('median wait')
        expect(waits.textContent).not.toContain('time spent red in CI')
        fireEvent.focus(within(screen.getByTestId('reviews-tiles')).getByText('median first review'))
        expect(
            (await screen.findAllByText(/1 reviewed PR had no ready time from GitHub and is left out\./u)).length,
        ).toBeGreaterThan(0)
    })

    it('tables each day of first reviews by wait, the newest first', async () => {
        await renderPage(REPORT)
        const row = await screen.findByTestId('reviews-day-2026-10-07')
        expect([...row.children].map((cell) => cell.textContent)).toEqual(['Oct 7', '0', '1', '0', '0', '1', '3.0h'])
    })

    it('lists who reviews, a trusted reviewer marked, reviews and wait each with a bar against the most', async () => {
        await renderPage(REPORT)
        const rows = within(await screen.findByTestId('reviews-reviewer-table')).getAllByTestId('reviews-reviewer')
        expect(rows.map((row) => [...row.children].slice(1).map((cell) => cell.textContent))).toEqual([
            ['2', '1', '0', '1', '3.0h'],
            ['1', '0', '2', '1', '–'],
        ])
        expect(rows.map((row) => within(row).queryByText('dana') !== null)).toEqual([true, false])
        expect(rows.map((row) => within(row).queryByText('trusted') !== null)).toEqual([true, false])
        // dana is the busiest and the slowest; carol left half as many and has no wait timed.
        expect(bars(rows[0])).toEqual(['100%', '100%'])
        expect(bars(rows[1])).toEqual(['50%', '0%'])
    })

    it("sets the planner's estimates in a panel apart from the plans, each plan's approval said", async () => {
        await renderPage(REPORT)
        const estimates = await screen.findByTestId('reviews-efforts')
        expect(within(estimates).getByRole('heading', { level: 2 }).textContent).toBe('Estimates')
        const efforts = within(estimates).getAllByTestId('reviews-effort')
        expect(efforts.map((row) => [...row.children].map((cell) => cell.textContent))).toEqual([
            ['small', '1', '2', '2.0', '$2.00'],
            ['medium', '1', '0', '0.0', '–'],
        ])
        const rounds = screen.getByTestId('reviews-round-panel')
        expect(within(rounds).getByRole('heading', { level: 2 }).textContent).toBe('Feedback rounds')
        expect(within(rounds).queryByTestId('reviews-effort-table')).toBeNull()
        const planned = screen.getByTestId('reviews-round-1')
        expect(planned.textContent).toContain('the planner')
        expect(within(planned).getByRole('link', { name: 'run:20' })).toBeTruthy()
        expect(screen.getByTestId('reviews-round-2').textContent).toContain('you, on the web')
    })

    it("heads canopy's reviewer with tiles, then its runs, dismissals by reason, and the trust line", async () => {
        await renderPage(REPORT)
        const tiles = await screen.findByTestId('reviews-canopy-tiles')
        expect(
            within(tiles)
                .getAllByRole('term')
                .map((t) => t.textContent),
        ).toEqual(['runs', 'cost', 'findings dismissed', 'drafts published'])
        expect(
            ['runs', 'cost', 'dismissed', 'published'].map(
                (key) => within(tiles).getByTestId(`reviews-canopy-${key}`).textContent,
            ),
        ).toEqual(['3', '$0.50', '1', '1'])
        expect(screen.getAllByTestId('reviews-run')).toHaveLength(2)
        const dismissals = screen.getAllByTestId('reviews-dismissal')
        expect(dismissals.map((row) => [...row.children].map((cell) => cell.textContent))).toEqual([['wrong', '1']])
        expect(screen.getByTestId('reviews-canopy-trust').textContent).toContain('without asking you')
    })

    it('lists each PR with its first review, rounds, and what they cost', async () => {
        await renderPage(REPORT)
        const [row] = within(await screen.findByTestId('reviews-pull-request-table')).getAllByTestId(
            'reviews-pull-request',
        )
        expect([...(row?.children ?? [])].slice(1).map((cell) => cell.textContent)).toEqual([
            'PROJ-1',
            '3.0h',
            '3',
            '1',
            '1',
            '2',
            '$2.50',
            '–',
        ])
    })

    it('says so when nothing happened', async () => {
        await renderPage({
            ...REPORT,
            reviews: 0,
            first_reviews: 0,
            median_first_review_hours: null,
            untimed: 0,
            reviewers: [],
            pull_requests: [],
            rounds: [],
            efforts: [],
            review_runs: [],
            dismissals: [],
            drafts: [],
        })
        expect(await screen.findByText('no reviews on no PRs · no first review timed over 7 days')).toBeTruthy()
        expect(screen.getByText("no first review on GitHub's clock came in these 7 days")).toBeTruthy()
        expect(screen.getByText("nobody left feedback on canopy's PRs in these 7 days")).toBeTruthy()
        // Estimates and Feedback rounds each say so.
        expect(screen.getAllByText('no feedback plan was written in these 7 days')).toHaveLength(2)
        expect(screen.getByText('canopy reviewed nothing in these 7 days')).toBeTruthy()
        expect(screen.queryByTestId('reviews-dismissal-table')).toBeNull()
    })
})
