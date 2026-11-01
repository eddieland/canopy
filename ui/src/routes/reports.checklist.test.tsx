import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { ChecklistCounts, ChecklistItemCounts } from '@/api/types'

import { Route } from './reports.checklist'

afterEach(() => {
    cleanup()
})

function item(id: string, extra: Partial<ChecklistItemCounts>): ChecklistItemCounts {
    return {
        repo: 'api',
        item: id,
        reminded: 12,
        passed: 0,
        fixed: 0,
        held: 0,
        not_applicable: 0,
        unanswered: 0,
        held_runs: [],
        fixed_runs: [],
        ...extra,
    }
}

// Two weeks of one list, in its order: an item held three times, by a worker's run and a task's among them; one that
// never failed in twelve runs; one mostly n/a; and one the runs fixed now and then.
const COUNTS: ChecklistCounts = {
    since: '2026-09-25T00:00:00Z',
    until: '2026-10-09T00:00:00Z',
    days: 14,
    repo: null,
    items: [
        item('newspaper', {
            passed: 9,
            held: 3,
            held_runs: [
                {
                    kind: 'run',
                    id: 42,
                    task_id: null,
                    started_at: '2026-10-08T10:00:00Z',
                    reason: 'The module keeps it.',
                },
                { kind: 'task', id: 2, task_id: 6, started_at: '2026-10-07T10:00:00Z', reason: null },
            ],
        }),
        item('doc-comments', { passed: 12 }),
        item('migration', { passed: 2, not_applicable: 9, unanswered: 1 }),
        item('general-types', { passed: 6, fixed: 4, unanswered: 2, fixed_runs: [] }),
    ],
    weeks: [
        {
            repo: 'api',
            item: 'newspaper',
            week: '2026-W40',
            reminded: 6,
            passed: 4,
            fixed: 0,
            held: 2,
            not_applicable: 0,
            unanswered: 0,
        },
        {
            repo: 'api',
            item: 'newspaper',
            week: '2026-W41',
            reminded: 6,
            passed: 5,
            fixed: 0,
            held: 1,
            not_applicable: 0,
            unanswered: 0,
        },
        {
            repo: 'api',
            item: 'doc-comments',
            week: '2026-W40',
            reminded: 6,
            passed: 6,
            fixed: 0,
            held: 0,
            not_applicable: 0,
            unanswered: 0,
        },
        {
            repo: 'api',
            item: 'doc-comments',
            week: '2026-W41',
            reminded: 6,
            passed: 6,
            fixed: 0,
            held: 0,
            not_applicable: 0,
            unanswered: 0,
        },
    ],
    previous: { since: '2026-09-11T00:00:00Z', until: '2026-09-25T00:00:00Z', reminded: 40, held: 1, unanswered: 3 },
}

/** The checklist page at `entry`, its two weeks' counts already read as `counts`. */
async function renderPage(entry = '/reports/checklist') {
    // Nothing reads the server: the counts are the ones set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.checklistCounts(COUNTS.days), COUNTS)
    const root = createRootRoute()
    const page = Route.update({
        id: '/reports/checklist',
        path: '/reports/checklist',
        getParentRoute: () => root,
    } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: [entry] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
    return router
}

/** Each item's row, as its name and the cells after it read. */
async function rows(): Promise<string[][]> {
    const table = await screen.findByTestId('checklist-table')
    return within(table)
        .getAllByTestId('checklist-item')
        .map((row) => [...row.children].map((cell) => cell.textContent))
}

describe('the checklist page', () => {
    it("opens on two weeks, each item's answers as a bar read out in words, then counts, then a verdict", async () => {
        await renderPage()
        expect(await screen.findByText('4 items in 1 repository over 14 days · 3 held')).toBeTruthy()
        expect(await rows()).toEqual([
            ['newspaper', '12', '9 pass · 3 held', '9', '0', '3', '0', '0', 'argue'],
            ['doc-comments', '12', '12 pass', '12', '0', '0', '0', '0', 'drop?'],
            ['migration', '12', '2 pass · 9 n/a · 1 unanswered', '2', '0', '0', '9', '1', 'drop?'],
            ['general-types', '12', '6 pass · 4 fixed · 2 unanswered', '6', '4', '0', '0', '2', ''],
        ])
        // The bar draws each answer given, and nothing for the rest.
        const bar = within(screen.getAllByTestId('checklist-bar')[0] ?? document.body)
        expect(bar.getByTestId('checklist-bar-passed').style.width).toBe('75%')
        expect(bar.getByTestId('checklist-bar-held').style.width).toBe('25%')
        expect(bar.queryByTestId('checklist-bar-fixed')).toBeNull()
        // Its legend once, under the table, in the table's order.
        expect(
            within(screen.getByTestId('checklist-legend'))
                .getAllByRole('listitem')
                .map((li) => li.textContent),
        ).toEqual(['pass', 'fixed', 'held', 'n/a', 'unanswered'])
    })

    it('opens the runs that held an item, a worker run and a task run, a reason under its run', async () => {
        await renderPage()
        fireEvent.click(await screen.findByRole('button', { name: '3 held: the runs' }))
        const runs = await screen.findByTestId('checklist-runs')
        expect(
            within(runs)
                .getAllByRole('link')
                .map((a) => [a.textContent, a.getAttribute('href')]),
        ).toEqual([
            ['run:42', '/workspace/runs/42'],
            ['task:6#2', '/tasks/6/runs/2'],
        ])
        expect(runs.textContent).toContain('The module keeps it.')
        // Two of the three: the server sends the newest twenty, and here it sent fewer than it counted.
        expect(screen.getByText(/the newest 2 of 3/u)).toBeTruthy()
        // A fixed count with no runs sent is a figure alone.
        expect(screen.queryByRole('button', { name: '4 fixed: the runs' })).toBeNull()
    })

    it("orders each list's items by the sort the search names, ties in the list's order", async () => {
        await renderPage('/reports/checklist?sort=na')
        expect((await rows()).map((r) => r[0])).toEqual(['migration', 'newspaper', 'doc-comments', 'general-types'])
        cleanup()
        const router = await renderPage('/reports/checklist?sort=unanswered')
        expect((await rows()).map((r) => r[0])).toEqual(['general-types', 'migration', 'newspaper', 'doc-comments'])
        fireEvent.click(screen.getByRole('radio', { name: 'list order' }))
        expect(await screen.findByRole('radio', { name: 'list order', checked: true })).toBeTruthy()
        expect(router.state.location.search).toEqual({})
    })

    it("shows the whole list's answers by week, or the picked item's, picked by its name", async () => {
        const router = await renderPage()
        const weeks = await screen.findByTestId('checklist-weeks')
        expect(within(weeks).getByTestId('checklist-weeks-of').textContent).toBe('every item')
        const total = () =>
            within(within(weeks).getByTestId('checklist-week-table'))
                .getAllByRole('row')
                .slice(1)
                .map((row) => [...row.children].map((cell) => cell.textContent))
        expect(total()).toEqual([
            ['W40', '12', '10', '0', '2', '0', '0'],
            ['W41', '12', '11', '0', '1', '0', '0'],
        ])
        fireEvent.click(screen.getByRole('link', { name: 'newspaper' }))
        expect(await within(weeks).findByText('api · newspaper')).toBeTruthy()
        expect(router.state.location.search).toEqual({ item: 'api:newspaper' })
        expect(total()).toEqual([
            ['W40', '6', '4', '0', '2', '0', '0'],
            ['W41', '6', '5', '0', '1', '0', '0'],
        ])
        fireEvent.click(within(weeks).getByRole('link', { name: 'every item' }))
        expect(await within(weeks).findByText('every item')).toBeTruthy()
    })
})
