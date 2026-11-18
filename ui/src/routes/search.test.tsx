import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { RuntimeSession, SearchResults, SessionList } from '@/api/types'
import { SESSIONS_PER_SEARCH } from '@/lib/sessions'

import { Route } from './search'

afterEach(cleanup)

const NOTHING: SearchResults = { words: ['lockfile'], hits: [], more: [] }

const BUILDING: NonNullable<SessionList['index']> = {
    sessions: 12,
    through: '2026-10-08T12:06:00Z',
    back_to: '2026-10-01T09:00:00Z',
    built: false,
    read_at: '2026-10-08T12:08:00Z',
    error: null,
    current: true,
    size_bytes: 2048,
}

/** A list of `whose` sessions found by the search's words at `text`, with `more` over it. */
function found(whose: SessionList['whose'], more: Partial<SessionList> = {}): SessionList {
    return {
        search: 'text',
        whose,
        words: ['lockfile'],
        sessions: [],
        more: false,
        progress: {
            status: 'found',
            read_at: '2026-10-08T12:08:00Z',
            error: null,
            through: '2026-10-08T12:06:00Z',
            current: true,
        },
        index: { ...BUILDING, built: true, back_to: null },
        why_titles: null,
        ...more,
    }
}

const HIT: RuntimeSession = {
    session_id: 'ses_deploy',
    parent_id: null,
    title: 'Why does the deploy script hang?',
    directory: '/home/op/acme/infra',
    started_at: '2026-10-08T11:12:00Z',
    updated_at: '2026-10-08T11:12:00Z',
    cost_usd: 0.84,
    archived: false,
    asked: null,
    models: [],
    made_by: null,
    reopen: null,
    subagents: [],
    snippet: [{ text: 'lockfile', marked: true }],
    more_messages: 0,
    cut: false,
}

/** The search page for `lockfile`, the journal holding nothing and each list of sessions already read as given. */
async function renderSearch(outside: SessionList, canopy: SessionList) {
    // Nothing reads the server: every read is set here.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.search('lockfile'), NOTHING)
    for (const list of [outside, canopy]) {
        client.setQueryData(keys.sessions({ whose: list.whose, q: 'lockfile', limit: SESSIONS_PER_SEARCH }), list)
    }
    const root = createRootRoute()
    const page = Route.update({ id: '/search', path: '/search', getParentRoute: () => root } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: ['/search?q=lockfile'] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
    await screen.findByTestId('search-results')
}

describe("the search page's sessions", () => {
    it('says how far the index has come when no session is found while it still builds', async () => {
        await renderSearch(found('outside', { index: BUILDING }), found('canopy', { index: BUILDING }))
        const panel = screen.getByTestId('search-sessions-unfound')
        expect(panel.textContent).toMatch(/No session found, though the index may not hold every one yet\./u)
        expect(panel.textContent).toMatch(/The index holds 12 sessions, .+; still building, back to /u)
    })

    it('shows no panel for sessions when none is found and the index is whole', async () => {
        await renderSearch(found('outside'), found('canopy'))
        expect(screen.queryByTestId('search-sessions-unfound')).toBeNull()
        expect(screen.queryByTestId('search-sessions-outside')).toBeNull()
    })

    it('leaves the index to the panel that found a session, at its foot', async () => {
        await renderSearch(found('outside', { index: BUILDING, sessions: [HIT] }), found('canopy', { index: BUILDING }))
        expect(screen.queryByTestId('search-sessions-unfound')).toBeNull()
        expect(screen.getByTestId('search-sessions-index').textContent).toMatch(/still building/u)
    })

    it('says only why text finds by titles where the index cannot be kept', async () => {
        const why = { search: 'titles', index: null, why_titles: 'SQLite 3.40 is too old.' } as const
        await renderSearch(found('outside', why), found('canopy', why))
        const said = screen.getByTestId('search-sessions-unfound').textContent
        expect(said).toContain('SQLite 3.40 is too old.')
        expect(said).not.toContain('yet')
    })
})
