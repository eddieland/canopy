import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { ToolsAgent, ToolsReport, ToolsRow, ToolsUse } from '@/api/types'

import { Route } from './reports.tools'

afterEach(() => {
    cleanup()
})

function used(by: string, counts: Partial<ToolsUse> = {}): ToolsUse {
    return {
        agent: by,
        offered: 4,
        partial: 0,
        called: 0,
        unoffered: 0,
        calls: 0,
        errors: 0,
        est_result_tokens: 0,
        ...counts,
    }
}

function row(name: string, counts: Partial<ToolsRow> = {}): ToolsRow {
    return {
        kind: 'tool',
        name,
        server: null,
        listed: true,
        unused: false,
        offered: 9,
        partial: 0,
        called: 0,
        unoffered: 0,
        calls: 0,
        errors: 0,
        est_result_tokens: 0,
        uses: [],
        ...counts,
    }
}

function agent(name: string, counts: Partial<ToolsAgent> = {}): ToolsAgent {
    return {
        agent: name,
        runs: 4,
        unanswered: 0,
        unasked: 0,
        servers: 2,
        tools: 2,
        unused: 2,
        calls: 62,
        errors: 5,
        est_result_tokens: 40_250,
        ...counts,
    }
}

// A week of two servers and two tools over a worker and a reviewer: the forge's server, which a few runs call, by the
// one tool of its a run called; an error tracker's, offered to the worker and never called; the shell, which every
// worker's run calls; and a tool nothing calls. The tasks' runs, the private worker's, have no offer on record, and
// called the shell all the same.
const REPORT: ToolsReport = {
    days: 7,
    since: '2026-10-02T00:00:00Z',
    until: '2026-10-09T00:00:00Z',
    servers: 2,
    tools: 2,
    unused: 2,
    calls: 77,
    errors: 6,
    runs: 13,
    unanswered: 1,
    unasked: 3,
    rows: [
        row('github', {
            kind: 'server',
            partial: 5,
            called: 2,
            calls: 12,
            est_result_tokens: 30_000,
            uses: [
                used('canopy-worker', { called: 2, calls: 12, est_result_tokens: 30_000 }),
                used('canopy-reviewer', { offered: 5, partial: 5 }),
            ],
        }),
        row('sentry', { kind: 'server', unused: true, offered: 4, uses: [used('canopy-worker')] }),
        row('github_pull_request_read', {
            server: 'github',
            listed: false,
            offered: 0,
            unoffered: 2,
            calls: 12,
            est_result_tokens: 30_000,
            uses: [used('canopy-worker', { offered: 0, unoffered: 2, calls: 12, est_result_tokens: 30_000 })],
        }),
        row('glob', {
            unused: true,
            uses: [used('canopy-worker'), used('canopy-reviewer', { offered: 5 })],
        }),
        row('shell', {
            called: 6,
            unoffered: 3,
            calls: 65,
            errors: 6,
            est_result_tokens: 14_000,
            uses: [
                used('canopy-worker', { called: 4, calls: 50, errors: 5, est_result_tokens: 10_250 }),
                used('canopy-worker-private', { offered: 0, unoffered: 3, calls: 8, est_result_tokens: 1_750 }),
                used('canopy-reviewer', { offered: 5, called: 2, calls: 7, errors: 1, est_result_tokens: 2_000 }),
            ],
        }),
    ],
    agents: [
        agent('canopy-worker', { servers: 2, unused: 2 }),
        agent('canopy-worker-private', {
            runs: 3,
            unasked: 3,
            servers: null,
            tools: null,
            unused: null,
            calls: 8,
            errors: 0,
            est_result_tokens: 1_750,
        }),
        agent('canopy-reviewer', {
            runs: 6,
            unanswered: 1,
            servers: 1,
            unused: 2,
            calls: 7,
            errors: 1,
            est_result_tokens: 2_000,
        }),
    ],
    previous: {
        since: '2026-09-25T00:00:00Z',
        until: '2026-10-02T00:00:00Z',
        servers: 2,
        tools: 1,
        unused: 0,
        calls: 70,
        errors: 6,
    },
}

/** The Tools report at `path`, its window's report already read as `report`; the router, to see where it goes. */
async function renderPage(report: ToolsReport, path = '/reports/tools') {
    // Nothing reads the server: the report is the one set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.toolsReport(report.days), report)
    const root = createRootRoute()
    const page = Route.update({ id: '/reports/tools', path: '/reports/tools', getParentRoute: () => root } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: [path] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
    return router
}

/** A table's rows as their cells' text: a bar's cell sits beside its figure's, empty for a screen reader. */
function cells(table: string, rows: RegExp): (string | null)[][] {
    return within(screen.getByTestId(table))
        .getAllByTestId(rows)
        .map((found) => [...found.children].map((cell) => cell.textContent))
}

describe('the Tools report', () => {
    it("says the window's state under its title", async () => {
        await renderPage(REPORT)
        expect(
            await screen.findByText('2 servers and 2 tools offered over 7 days · 2 never called · 77 calls, 6 failed'),
        ).toBeTruthy()
    })

    it("heads the page with the window's figures, each beside the window before's", async () => {
        await renderPage(REPORT)
        const tiles = await screen.findByTestId('tools-tiles')
        expect(within(tiles).getByText('offered')).toBeTruthy()
        expect(within(tiles).getByText('never called')).toBeTruthy()
        expect(tiles.textContent).toContain('77')
    })

    it('lists the agents by their calls, what an agent with no offer was offered not known', async () => {
        await renderPage(REPORT)
        await screen.findByTestId('tools-agent-table')
        expect(cells('tools-agent-table', /^tools-agent-canopy/u)).toEqual([
            ['canopy-worker', '4', '0', '2', '2', '2', '62', '', '5', '40.3k'],
            ['canopy-worker-private', '3', '3', '–', '–', '–', '8', '', '0', '1.8k'],
            ['canopy-reviewer', '6', '1', '1', '2', '2', '7', '', '1', '2.0k'],
        ])
        expect(screen.getByTestId('tools-offers').textContent).toContain('No offer on record for 4 of 13 runs')
    })

    it('lists each server and tool by its calls, one offered and never called reading never', async () => {
        await renderPage(REPORT)
        await screen.findByTestId('tools-row-table')
        expect(cells('tools-row-table', /^tools-row-/u)).toEqual([
            ['shell', 'built in', '9', '67%', '65', '', '6', '14.0k'],
            ['github', 'MCP server', '9', '22%', '12', '', '0', '30.0k'],
            // A server's tool is in no offer by name: no count of runs offered it, and no rate.
            ['github_pull_request_read', 'of github', '–', '–', '12', '', '0', '30.0k'],
            ['glob', 'built in', '9', 'never', '0', '', '0', '0'],
            ['sentry', 'MCP server', '4', 'never', '0', '', '0', '0'],
        ])
        expect(screen.getByTestId('tools-count').textContent).toBe('5')
        expect(screen.getByTestId('tools-names').textContent).toContain('An offer names a server, not its tools')
    })

    it('narrows the rows to an agent picked by its name, and widens them again', async () => {
        const router = await renderPage(REPORT)
        const agents = await screen.findByTestId('tools-agent-table')
        fireEvent.click(within(agents).getByRole('link', { name: 'canopy-reviewer' }))
        await waitFor(() => {
            expect(router.state.location.search).toEqual({ agent: 'canopy-reviewer' })
        })
        expect(screen.getByTestId('tools-scope').textContent).toBe('canopy-reviewer')
        expect(screen.getByTestId('tools-count').textContent).toBe('3 of 5')
        // Its own runs alone: the server a worker called and it never did reads never for it.
        expect(cells('tools-row-table', /^tools-row-/u)).toEqual([
            ['shell', 'built in', '5', '40%', '7', '', '1', '2.0k'],
            ['github', 'MCP server', '5', 'never', '0', '', '0', '0'],
            ['glob', 'built in', '5', 'never', '0', '', '0', '0'],
        ])
        expect(within(agents).getByRole('link', { name: 'canopy-reviewer' }).getAttribute('aria-current')).toBe('page')
        fireEvent.click(within(screen.getByTestId('tools-rows')).getByRole('link', { name: 'every agent' }))
        await waitFor(() => {
            expect(router.state.location.search).toEqual({})
        })
        expect(screen.getByTestId('tools-count').textContent).toBe('5')
    })

    it('orders the rows from the header, kept in the search', async () => {
        const router = await renderPage(REPORT)
        fireEvent.click(await screen.findByTestId('tools-sort-least'))
        await waitFor(() => {
            expect(router.state.location.search).toEqual({ order: 'least' })
        })
        const heads = within(screen.getByTestId('tools-row-table'))
            .getAllByRole('rowheader')
            .map((head) => head.textContent)
        expect(heads).toEqual(['glob', 'sentry', 'github', 'shell', 'github_pull_request_read'])
    })

    it('reads an agent the window does not have as every agent', async () => {
        await renderPage(REPORT, '/reports/tools?agent=nobody')
        await screen.findByTestId('tools-row-table')
        expect(screen.getByTestId('tools-scope').textContent).toBe('every agent')
    })

    it('says so when no agent ran', async () => {
        await renderPage({
            ...REPORT,
            servers: 0,
            tools: 0,
            unused: 0,
            calls: 0,
            errors: 0,
            runs: 0,
            unanswered: 0,
            unasked: 0,
            rows: [],
            agents: [],
        })
        expect(await screen.findByText('no server or tool offered over 7 days')).toBeTruthy()
        expect(screen.getByText('no agent ran in these 7 days')).toBeTruthy()
        expect(screen.getByText('no server or tool was offered or called in these 7 days')).toBeTruthy()
    })

    it('reads 30 days from the search, as the reports page links it', async () => {
        await renderPage({ ...REPORT, days: 30 }, '/reports/tools?days=30')
        expect(await screen.findByText(/offered over 30 days/u)).toBeTruthy()
    })
})
