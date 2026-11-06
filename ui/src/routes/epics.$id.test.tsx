import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mockEpicDetails } from '@/api/mocks'
import { keys } from '@/api/queries'

import { Route } from './epics.$id'

// Half an hour after the mock journal's T0, as the screenshots are taken: epic 1 was submitted 12h before.
const NOW = new Date('2026-10-08T12:30:00Z')

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
})

afterEach(() => {
    cleanup()
    vi.useRealTimers()
})

/**
 * An epic's page at `id`, every mock epic already read. Every query is enabled, as on the page, and nothing is stale,
 * so only a query the page starts that has no data reads the server; what the shell's parts read (the attention list,
 * the latest tick, the server's meta) is read already.
 */
async function renderPage(id: string): Promise<QueryClient> {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
    client.setQueryData(keys.attention, [])
    client.setQueryData(keys.tick, { tick: null, acknowledged: null })
    client.setQueryData(keys.meta, {})
    for (const detail of mockEpicDetails) {
        client.setQueryData(keys.epic(detail.epic.id), detail)
    }
    const root = createRootRoute()
    const page = Route.update({ id: '/epics/$id', path: '/epics/$id', getParentRoute: () => root } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: [`/epics/${id}`] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
    return client
}

/** The one line of text, among the page's, that reads `text` whole and starts with it, its deepest holder. */
function line(text: string): HTMLElement {
    return screen.getByText(
        (_, element) =>
            element !== null &&
            element.textContent.startsWith(text) &&
            ![...element.children].some((child) => child.textContent.startsWith(text)),
    )
}

describe("an epic's page", () => {
    it("heads it with the epic, its goal's first line, its standing, what's filed, and its bound", async () => {
        await renderPage('1')
        const title = await screen.findByRole('heading', { level: 1 })
        expect(title.textContent).toBe(
            'epic:1 Move billing to the v2 API everywhere it is called, web and mobile both, and retire v1 once ' +
                'nothing reads it.',
        )
        expect(line('approved ·').textContent).toBe(
            'approved · 2 of 4 entries filed · members 3 of at most 8 · submitted 12h ago',
        )
    })

    it.each([1, 2])("opens epic:%i's plan from its header", async (id) => {
        await renderPage(String(id))
        const open = await screen.findByRole('link', { name: 'Open plan' })
        expect(open.getAttribute('href')).toBe(`/epics/${String(id)}/plan`)
    })

    it('says a stopped epic is stopped, and when, and offers no stop', async () => {
        await renderPage('4')
        await screen.findByTestId('epic-board')
        expect(line('stopped ').textContent).toBe(
            'stopped 31m ago · no breakdown · members 0 of at most 8 · submitted 31m ago',
        )
        expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
        expect(screen.getByText('no plan: you stopped it, and no plan run of it starts again')).toBeTruthy()
    })

    it('offers Stop, and Stop now while its plan run works, beside Open plan', async () => {
        await renderPage('3')
        await screen.findByTestId('epic-board')
        const actions = within(screen.getByTestId('epic-actions'))
        expect(actions.getAllByRole('button').map((button) => button.textContent)).toEqual(['Stop', 'Stop now'])
        cleanup()
        await renderPage('2')
        await screen.findByTestId('epic-board')
        expect(screen.getByTestId('epic-actions').textContent).toBe('Open planStop')
    })

    it('offers no plan to open before a plan run records one', async () => {
        await renderPage('3')
        await screen.findByTestId('epic-board')
        expect(screen.queryByRole('link', { name: 'Open plan' })).toBeNull()
    })

    it('leads with the breakdown, then its conversation, requirements and contracts, and plan runs', async () => {
        await renderPage('1')
        await screen.findByTestId('epic-board')
        expect(screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent)).toEqual([
            'Breakdown',
            'Conversation',
            'Requirements and contracts',
            'Plan runs',
        ])
        expect(within(screen.getByTestId('epic-runs')).getByText('epic:1#1')).toBeTruthy()
    })

    it.each(['abc', '0', '1.5', '9007199254740993'])(
        'names no epic at %s, and asks the server for none',
        async (id) => {
            const client = await renderPage(id)
            expect((await screen.findByText(`canopy has no epic:${id}`)).textContent).toBe(`canopy has no epic:${id}`)
            expect(screen.queryByTestId('epic-board')).toBeNull()
            // Nothing read an epic for it: no epic's query but the ones set here was ever fetched, or is being.
            const asked = client
                .getQueryCache()
                .findAll({ queryKey: ['epic'] })
                .filter((query) => query.state.dataUpdateCount === 0)
            expect(asked.map((query) => query.state.fetchStatus)).toEqual(asked.map(() => 'idle'))
            expect(
                asked.every((query) => query.state.errorUpdateCount === 0 && query.state.fetchFailureCount === 0),
            ).toBe(true)
        },
    )
})
