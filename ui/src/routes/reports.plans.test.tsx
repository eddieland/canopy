import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { PlansReport, PlansRow } from '@/api/types'
import { tipOf } from '@/test-utils'

import { Route } from './reports.plans'

afterEach(() => {
    cleanup()
})

// A plan row, `over` its fields.
function row(over: Partial<PlansRow> & Pick<PlansRow, 'plan_id' | 'outcome'>): PlansRow {
    return {
        ticket_key: 'PROJ-1',
        run_id: 20 + over.plan_id,
        created_at: '2026-10-07T09:00:00Z',
        size: 6_144,
        effort: 'small',
        level: 'strict',
        approved_at: null,
        hours_to_approve: null,
        edited: false,
        comments: 0,
        earlier: 0,
        implemented: false,
        resumes: 0,
        reasons: {},
        done: false,
        cost_usd: null,
        ...over,
    }
}

// 30 days: a plan its planner approved at strict whose PR needed two resumes, one you approved as written, one you
// revised after sending another back, and one waiting.
const REPORT: PlansReport = {
    days: 30,
    since: '2026-09-09T00:00:00Z',
    until: '2026-10-09T00:00:00Z',
    level: 'strict',
    plans: [
        row({ plan_id: 5, outcome: 'waiting' }),
        row({
            plan_id: 4,
            ticket_key: 'PROJ-4',
            outcome: 'planner',
            approved_at: '2026-10-07T09:00:00Z',
            hours_to_approve: 0,
            size: 2_048,
            implemented: true,
            resumes: 2,
            reasons: { ci: 1, review: 1 },
        }),
        row({
            plan_id: 3,
            ticket_key: 'PROJ-3',
            level: 'off',
            outcome: 'revised',
            approved_at: '2026-10-07T12:00:00Z',
            hours_to_approve: 3,
            size: 20_000,
            edited: true,
            earlier: 1,
            implemented: true,
            done: true,
        }),
        row({ plan_id: 2, ticket_key: 'PROJ-3', level: 'off', outcome: 'replaced', comments: 2 }),
        row({
            plan_id: 1,
            ticket_key: 'PROJ-2',
            level: null,
            outcome: 'as_written',
            approved_at: '2026-10-07T10:00:00Z',
            hours_to_approve: 1,
            implemented: true,
            done: true,
        }),
    ],
    groups: [
        {
            level: 'off',
            outcome: 'revised',
            plans: 1,
            median_hours_to_approve: 3,
            median_size: 20_000,
            implemented: 1,
            with_resume: 0,
            resumes: 0,
            done: 1,
        },
        {
            level: 'strict',
            outcome: 'planner',
            plans: 1,
            median_hours_to_approve: 0,
            median_size: 2_048,
            implemented: 1,
            with_resume: 1,
            resumes: 2,
            done: 0,
        },
        {
            level: null,
            outcome: 'as_written',
            plans: 1,
            median_hours_to_approve: 1,
            median_size: 6_144,
            implemented: 1,
            with_resume: 0,
            resumes: 0,
            done: 1,
        },
    ],
    lengths: [
        { low: 3_000, high: 6_000, plans: 1, median_hours_to_approve: 1, as_written: 1 },
        { low: 12_000, high: null, plans: 1, median_hours_to_approve: 3, as_written: 0 },
    ],
    page_bytes: 3_000,
    outcomes: { planner: 1, as_written: 1, revised: 1, replaced: 1, dropped: 0, waiting: 1 },
}

/** The Plans page at `/reports/plans`, its 30 days' report already read as `report`. */
async function renderPage(report: PlansReport) {
    // Nothing reads the server: the report is the one set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.plansReport(report.days), report)
    const root = createRootRoute()
    const page = Route.update({ id: '/reports/plans', path: '/reports/plans', getParentRoute: () => root } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: ['/reports/plans'] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
}

// A table row's cells' text, its head's first.
function texts(element: HTMLElement | undefined): (string | null)[] {
    return [...(element?.children ?? [])].map((cell) => cell.textContent)
}

// A table row's cells' text, after its head.
function cells(element: HTMLElement | undefined): (string | null)[] {
    return texts(element).slice(1)
}

describe('the Plans page', () => {
    it("says the window's state under its title, the key's level now, and what it cannot see", async () => {
        await renderPage(REPORT)
        expect(
            await screen.findByText('5 plans · 3 approved, 1 by the planner · 1 of 3 PRs needed a resume over 30 days'),
        ).toBeTruthy()
        expect(screen.getByTestId('plans-key').textContent).toBe(
            'policy.planner_may_approve is strict now. 1 plan sent back, 1 waiting on you.',
        )
        expect(screen.getByTestId('plans-limits').textContent).toContain('shows as not recorded')
    })

    it('tables the approvals by level and how each went ahead, with the PRs that needed a resume', async () => {
        await renderPage(REPORT)
        const groups = within(await screen.findByTestId('plans-group-table')).getAllByTestId('plans-group')
        expect(groups.map((g) => texts(g))).toEqual([
            ['off', 'revised', '1', '3.0h', '≈ 6½ pages', '0 of 1', '0', '1'],
            ['strict', 'by the planner', '1', '–', '≈ ½ page', '1 of 1', '2', '0'],
            ['not recorded', 'as written', '1', '1.0h', '≈ 2 pages', '0 of 1', '0', '1'],
        ])
        // The bytes behind a length are on its hover.
        expect(tipOf(within(groups[0] as HTMLElement).getByText('≈ 6½ pages'))).toBe('19.5 KiB')
    })

    it('tables the time you took to approve by length', async () => {
        await renderPage(REPORT)
        const lengths = within(await screen.findByTestId('plans-length-table')).getAllByTestId('plans-length')
        expect(lengths.map((n) => texts(n))).toEqual([
            ['1–2 pages', '1', '1.0h', '1'],
            ['4 pages and up', '1', '3.0h', '0'],
        ])
        expect(tipOf(within(lengths[1] as HTMLElement).getByText('4 pages and up'))).toBe('11.7 KiB and up')
    })

    it('lists each plan with its level, how it went and what changed, and the resumes after it', async () => {
        await renderPage(REPORT)
        const planned = await screen.findByTestId('plans-plan-4')
        expect(within(planned).getByRole('link', { name: 'run:24' })).toBeTruthy()
        expect(cells(planned).slice(0, 6)).toEqual(['PROJ-4', 'strict', 'by the planner', '≈ ½ page', '–', '2'])
        expect(tipOf(within(planned).getByText('2'))).toBe('ci 1, review 1')
        expect(cells(screen.getByTestId('plans-plan-3')).slice(1, 3)).toEqual([
            'off',
            'revised: edited, after 1 sent back',
        ])
        expect(cells(screen.getByTestId('plans-plan-2')).slice(2, 3)).toEqual(['sent back: 2 comments'])
        // Nothing implemented it: no resumes to count.
        expect(tipOf(within(screen.getByTestId('plans-plan-5')).getByText('–', { selector: 'td span' }))).toBe(
            'No implement followed it',
        )
    })

    it('says so when no plan was written', async () => {
        await renderPage({
            ...REPORT,
            plans: [],
            groups: [],
            lengths: [],
            outcomes: { planner: 0, as_written: 0, revised: 0, replaced: 0, dropped: 0, waiting: 0 },
        })
        expect(await screen.findByText('no plans over 30 days')).toBeTruthy()
        expect(screen.getByText('no plan was approved in these 30 days')).toBeTruthy()
        expect(screen.getByText('you approved no plan in these 30 days')).toBeTruthy()
        expect(screen.getByText('no plan was written in these 30 days')).toBeTruthy()
    })
})
