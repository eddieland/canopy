import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockEpics } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { EpicSummary } from '@/api/types'

import { Route } from './epics.index'

afterEach(() => {
    cleanup()
})

/** The epics page, its list already read as `epics`. */
async function renderPage(epics: EpicSummary[]) {
    // Nothing reads the server: the list is the one set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.epics, epics)
    const root = createRootRoute()
    const page = Route.update({ id: '/epics/', path: '/epics', getParentRoute: () => root } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: ['/epics'] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
}

describe('the epics page', () => {
    it('lists a row per epic, the newest first, as the server sends them', async () => {
        await renderPage(mockEpics)
        const list = await screen.findByTestId('epics')
        expect(
            within(list)
                .getAllByRole('listitem')
                .map((row) => within(row).getByText(/^epic:\d+$/u).textContent),
        ).toEqual(['epic:3', 'epic:2', 'epic:1'])
        expect(screen.getByTestId('epics-count').textContent).toBe('3 epics')
    })

    it('names the command that submits one while there are none', async () => {
        await renderPage([])
        const empty = await screen.findByText(/^no epics yet/u)
        expect(empty.textContent).toBe('no epics yet: canopy epic submit TEXT hands canopy one')
        expect(screen.queryByTestId('epics')).toBeNull()
    })
})
