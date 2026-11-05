import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockEpicDetails } from '@/api/mocks'
import { keys } from '@/api/queries'

import { Route } from './epics.$id'

afterEach(() => {
    cleanup()
})

/** An epic's page at `id`, every mock epic already read. */
async function renderPage(id: string) {
    // Nothing reads the server: the epics are the ones set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
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
}

describe("an epic's page", () => {
    it("heads it with the epic, its goal's first line, its standing, what's filed, and its bound", async () => {
        await renderPage('1')
        const title = await screen.findByRole('heading', { level: 1 })
        expect(title.textContent).toBe(
            'epic:1 Move billing to the v2 API everywhere it is called, web and mobile both, and retire v1 once ' +
                'nothing reads it.',
        )
        const header = title.closest('header') ?? document.body
        expect(header.textContent).toContain('approved · 2 of 4 entries filed · members 3 of at most 8 · submitted')
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

    it.each(['abc', '0', '1.5'])('names no epic at %s, and asks the server for none', async (id) => {
        await renderPage(id)
        expect((await screen.findByText(`canopy has no epic:${id}`)).textContent).toBe(`canopy has no epic:${id}`)
        expect(screen.queryByTestId('epic-board')).toBeNull()
    })
})
