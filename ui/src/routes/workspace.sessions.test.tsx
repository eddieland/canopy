import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { keys } from '@/api/queries'
import type { SessionsFind } from '@/api/queries'
import type { RuntimeSession, SessionList, SessionRun } from '@/api/types'

import { Route } from './workspace.sessions'

beforeEach(() => {
    // The clipboard needs a secure context, which happy-dom is not: without one, no copy button renders.
    vi.stubGlobal('isSecureContext', true)
})

afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
})

const READ: SessionList['progress'] = {
    status: 'found',
    read_at: '2026-10-08T12:08:00Z',
    error: null,
    through: '2026-10-08T12:06:00Z',
    current: true,
}

/** A session outside canopy, or with `made_by` one of canopy's, started at `at`. */
function session(id: string, title: string | null, at: string, more: Partial<RuntimeSession> = {}): RuntimeSession {
    return {
        session_id: id,
        parent_id: null,
        title,
        directory: '/home/op/acme/infra',
        started_at: at,
        updated_at: at,
        cost_usd: 0.84,
        archived: false,
        made_by: null,
        reopen: `cd /home/op/acme/infra && opencode --session ${id}`,
        subagents: [],
        ...more,
    }
}

/** The run of canopy's that made a session, of `kind`, with what its page needs. */
function ran(kind: SessionRun['kind'], id: number, more: Partial<SessionRun> = {}): Partial<RuntimeSession> {
    return {
        made_by: { kind, id, ticket_key: null, chore: null, task_id: null, epic_id: null, ...more },
        reopen: null,
        directory: '/work/acme',
    }
}

const OUTSIDE: SessionList = {
    search: 'titles',
    whose: 'outside',
    words: [],
    more: false,
    progress: READ,
    sessions: [
        session('ses_deploy', 'Why does the deploy script hang on staging?', '2026-10-08T11:12:00Z', {
            subagents: [
                session('ses_find', 'Find where deploy.sh waits', '2026-10-08T11:20:00Z', { parent_id: 'ses_deploy' }),
            ],
        }),
        session('ses_untitled', null, '2026-10-08T08:50:00Z', { directory: '/home/op/notes' }),
    ],
}

const CANOPYS: SessionList = {
    ...OUTSIDE,
    whose: 'canopy',
    sessions: [
        session('ses_tick2', 'tick 2 · timer', '2026-10-08T11:00:00Z', ran('tick', 2)),
        session('ses_mock41', 'ABC-101 implement: Sign in with SSO', '2026-10-08T12:00:00Z', {
            ...ran('run', 41, { ticket_key: 'ABC-101' }),
        }),
        session('ses_review4', 'review https://github.com/acme/web/pull/88', '2026-10-08T10:20:00Z', ran('review', 4)),
        session('ses_chore2', 'chore deps', '2026-10-08T10:00:00Z', ran('chore_run', 2, { chore: 'deps' })),
        session('ses_task5', 'task 6', '2026-10-08T09:00:00Z', ran('task_run', 5, { task_id: 6 })),
        session('ses_epic4', 'epic 3 plan', '2026-10-08T08:00:00Z', ran('epic_run', 4, { epic_id: 3 })),
    ],
}

/** The sessions page at `at`, each list it asks for already read as `lists` gives it, by whose. */
async function renderPage(at: string, lists: Partial<Record<SessionList['whose'], SessionList>>) {
    // Nothing reads the server: the lists are the ones set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    for (const [whose, list] of Object.entries(lists)) {
        for (const archived of [false, true]) {
            for (const limit of [50, 500]) {
                const find: SessionsFind = { whose: whose === 'canopy' ? 'canopy' : 'outside', archived, limit }
                client.setQueryData(keys.sessions(find), list)
            }
        }
    }
    const root = createRootRoute()
    const page = Route.update({
        id: '/workspace/sessions',
        path: '/workspace/sessions',
        getParentRoute: () => root,
    } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: [at] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
}

function rows() {
    return within(screen.getByTestId('sessions')).getAllByTestId('session')
}

describe('the sessions page', () => {
    it('opens on the sessions outside canopy, a subagent under the one it ran for, each with its command', async () => {
        await renderPage('/workspace/sessions', { outside: OUTSIDE })
        expect(await screen.findByRole('heading', { name: 'Sessions outside canopy' })).toBeTruthy()
        expect(rows().map((r) => r.textContent)).toEqual([
            expect.stringContaining('Why does the deploy script hang on staging?'),
            expect.stringContaining('Find where deploy.sh waits'),
            expect.stringContaining('no title'),
        ])
        const sub = within(rows()[1] ?? document.body)
        // The indent shows its parent to the eye; its chip names it to a screen reader.
        expect(sub.getByText('subagent').textContent).toBe('subagent of Why does the deploy script hang on staging?')
        expect(sub.getByText('cd /home/op/acme/infra && opencode --session ses_find')).toBeTruthy()
        // Each copy button names the session it copies the command of; one with no title by its id.
        expect(sub.getByRole('button', { name: 'Copy reopen command of Find where deploy.sh waits' })).toBeTruthy()
        expect(
            within(rows()[2] ?? document.body).getByRole('button', {
                name: 'Copy reopen command of session ses_untitled',
            }),
        ).toBeTruthy()
        // A directory's end, its whole on hover, so the title keeps the width.
        expect(within(rows()[0] ?? document.body).getByText('…/acme/infra')).toBeTruthy()
        expect(screen.getByTestId('sessions-count').textContent).toBe('3')
        const archived = screen.getByRole('link', { name: 'archived' })
        expect(archived.getAttribute('aria-pressed')).toBe('false')
        expect(archived.getAttribute('aria-current')).toBeNull()
        expect(screen.getByTestId('sessions-progress').textContent).toMatch(
            /^Read every session updated up to .*last read/u,
        )
    })

    it("lists canopy's behind a filter, each opening the page of the run that made it", async () => {
        await renderPage('/workspace/sessions?canopy=true', { canopy: CANOPYS })
        expect(await screen.findByRole('heading', { name: "canopy's sessions" })).toBeTruthy()
        const hrefs = rows().map((r) => within(r).getAllByRole('link')[0]?.getAttribute('href'))
        expect(hrefs).toEqual([
            '/workspace/ticks/2',
            '/workspace/runs/41',
            '/pull-requests/reviews/4',
            '/chores/deps/runs/2',
            '/tasks/6/runs/5',
            '/epics/3',
        ])
        // None of canopy's has a command to copy: its page is the way back.
        expect(screen.queryByText(/opencode --session/u)).toBeNull()
        const whose = screen.getByRole('navigation', { name: 'Whose sessions' })
        const outside = within(whose).getByRole('link', { name: 'outside canopy' })
        expect(outside.getAttribute('href')).toBe('/workspace/sessions')
        // Only the chosen chip is the current page, though the default's search is a part of this one's.
        expect(outside.getAttribute('aria-current')).toBeNull()
        expect(within(whose).getByRole('link', { name: "canopy's" }).getAttribute('aria-current')).toBe('page')
    })

    it('presses archived while the archived are listed, and never marks it the current page', async () => {
        await renderPage('/workspace/sessions?archived=true', { outside: OUTSIDE })
        const archived = await screen.findByRole('link', { name: 'archived' })
        expect(archived.getAttribute('aria-pressed')).toBe('true')
        expect(archived.getAttribute('aria-current')).toBeNull()
        expect(archived.getAttribute('href')).toBe('/workspace/sessions')
    })

    it('lists none while sessions.search is off, and says how to turn it on', async () => {
        const off: SessionList = {
            search: 'off',
            whose: 'outside',
            words: [],
            sessions: [],
            more: false,
            progress: null,
        }
        await renderPage('/workspace/sessions', { outside: off })
        expect(await screen.findByText(/in your private config/u)).toBeTruthy()
        expect(screen.queryByTestId('sessions')).toBeNull()
        expect(screen.queryByTestId('sessions-count')).toBeNull()
    })

    it('says when more match than it lists, and links to the longest list', async () => {
        await renderPage('/workspace/sessions', { outside: { ...OUTSIDE, more: true } })
        expect((await screen.findByTestId('sessions-count')).textContent).toBe('newest 3')
        const more = screen.getByRole('link', { name: 'list up to 500' })
        expect(more.getAttribute('href')).toBe('/workspace/sessions?all=true')
    })

    it('links back to the newest 50 from the longest list, in the same place', async () => {
        await renderPage('/workspace/sessions?all=true', { outside: OUTSIDE })
        const back = await screen.findByRole('link', { name: 'list the newest 50' })
        expect(back.getAttribute('href')).toBe('/workspace/sessions')
    })

    it('says the loop has read nothing yet, before its first read', async () => {
        const unread: SessionList = {
            ...OUTSIDE,
            sessions: [],
            progress: { status: null, read_at: null, error: null, through: null, current: false },
        }
        await renderPage('/workspace/sessions', { outside: unread })
        expect(await screen.findByText(/^no sessions yet: canopy loop reads/u)).toBeTruthy()
    })
})
