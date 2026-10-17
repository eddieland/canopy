import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { keys } from '@/api/queries'
import type { Session } from '@/api/types'
import { setBuddy } from '@/lib/buddy'
import { FakeEventSource } from '@/test-utils'

import { AppShell } from './app-shell'

const SIGNED_IN: Session = { signed_in: true, token: 'tok' }
const SIGNED_OUT: Session = { signed_in: false, token: null }

// Stubs matchMedia so the window is as wide as a whole rail needs when `wide`, and lets a test resize it later.
function stubWidth(wide: boolean): { set: (wide: boolean) => void } {
    let matches = wide
    const listeners = new Set<() => void>()
    vi.stubGlobal(
        'matchMedia',
        vi.fn((query: string) => ({
            get matches() {
                return query.includes('min-width') && matches
            },
            media: query,
            addEventListener: (_: string, listener: () => void) => listeners.add(listener),
            removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
        })),
    )
    return {
        set(next) {
            matches = next
            for (const listener of listeners) {
                listener()
            }
        },
    }
}

beforeEach(() => {
    localStorage.clear()
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource)
})

afterEach(() => {
    cleanup()
    // Sprig's setting is the page's, kept past a test: put it back as a fresh page has it.
    setBuddy('off')
    localStorage.clear()
})

// The shell as the root of a router at `at`, under a query client that holds `session`, or nothing yet, and fetches
// nothing: every list the shell shows stays as a skeleton.
async function renderShell(session: Session | undefined, at = '/attention') {
    const client = new QueryClient()
    client.setQueryDefaults([], { enabled: false })
    if (session !== undefined) {
        client.setQueryData(keys.session, session)
    }
    const root = createRootRoute({ component: AppShell })
    const router = createRouter({
        routeTree: root.addChildren([
            createRoute({ getParentRoute: () => root, path: '/attention', component: () => <h1>What needs you</h1> }),
            createRoute({ getParentRoute: () => root, path: '/runs', component: () => <h1>Runs</h1> }),
        ]),
        history: createMemoryHistory({ initialEntries: [at] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router} />
        </QueryClientProvider>,
    )
    return router
}

describe('AppShell', () => {
    it('shows nothing, and opens no stream, before it knows whether the browser is signed in', async () => {
        stubWidth(true)
        await renderShell(undefined)
        expect(screen.queryByRole('form', { name: 'Sign in' })).toBeNull()
        expect(screen.queryByRole('navigation')).toBeNull()
        expect(FakeEventSource.instances).toEqual([])
    })

    it('shows the sign-in page whatever the route when signed out, and opens no stream', async () => {
        stubWidth(true)
        await renderShell(SIGNED_OUT)
        expect(screen.getByRole('form', { name: 'Sign in' })).toBeDefined()
        expect(screen.queryByRole('heading', { name: 'What needs you' })).toBeNull()
        expect(screen.queryByRole('navigation')).toBeNull()
        expect(FakeEventSource.instances).toEqual([])
    })

    it("signed in, frames the page with the rail and the header, and opens the server's stream", async () => {
        stubWidth(true)
        await renderShell(SIGNED_IN)
        expect(screen.getByRole('heading', { name: 'What needs you' })).toBeDefined()
        expect(screen.getByRole('navigation', { name: 'Main' })).toBeDefined()
        expect(screen.getByRole('searchbox', { name: 'Search the journal' })).toBeDefined()
        expect(screen.getByRole('region', { name: 'Working' })).toBeDefined()
        expect(screen.queryByRole('button', { name: 'Open the rail' })).toBeNull()
        expect(FakeEventSource.instances.map((source) => source.url)).toEqual(['/api/events'])
    })

    it('shows Sprig in the rail once Settings turns it on, and leaves it out once told not to show tips', async () => {
        stubWidth(true)
        await renderShell(SIGNED_IN)
        expect(screen.queryByRole('complementary', { name: 'Sprig' })).toBeNull()

        act(() => setBuddy('on'))
        fireEvent.click(screen.getByRole('button', { name: "Don't show me tips again" }))
        expect(screen.queryByRole('complementary', { name: 'Sprig' })).toBeNull()
    })

    describe('in a window too narrow for the whole rail', () => {
        it('shows the nav as a strip, and opens the whole rail over the page from its button', async () => {
            stubWidth(false)
            await renderShell(SIGNED_IN)
            expect(screen.getByRole('link', { name: 'Runs' })).toBeDefined()
            expect(screen.queryByRole('searchbox')).toBeNull()

            fireEvent.click(screen.getByRole('button', { name: 'Open the rail' }))
            expect(screen.getByRole('dialog', { name: 'Rail' })).toBeDefined()
            expect(screen.getByRole('searchbox', { name: 'Search the journal' })).toBeDefined()
        })

        it('opens the rail on `/`, landing in its search box', async () => {
            stubWidth(false)
            await renderShell(SIGNED_IN)

            fireEvent.keyDown(document.body, { key: '/' })
            expect(screen.getByRole('dialog', { name: 'Rail' })).toBeDefined()
            expect(document.activeElement).toBe(screen.getByRole('searchbox', { name: 'Search the journal' }))
        })

        it('closes the rail when a link in it is followed, which leaves for another page', async () => {
            stubWidth(false)
            const router = await renderShell(SIGNED_IN)
            fireEvent.click(screen.getByRole('button', { name: 'Open the rail' }))

            const sheet = screen.getByRole('dialog', { name: 'Rail' })
            await act(async () => {
                fireEvent.click(within(sheet).getByRole('link', { name: 'Runs' }))
                await Promise.resolve()
            })
            expect(screen.queryByRole('dialog', { name: 'Rail' })).toBeNull()
            expect(router.state.location.pathname).toBe('/runs')
        })

        it('closes the rail when a search is sent from it', async () => {
            stubWidth(false)
            const router = await renderShell(SIGNED_IN)
            fireEvent.keyDown(document.body, { key: '/' })

            const box = screen.getByRole('searchbox', { name: 'Search the journal' })
            fireEvent.change(box, { target: { value: 'csv' } })
            await act(async () => {
                fireEvent.submit(box)
                await Promise.resolve()
            })
            expect(screen.queryByRole('dialog', { name: 'Rail' })).toBeNull()
            expect(router.state.location.href).toBe('/search?q=csv')
        })

        it('closes the sheet on widening to a whole rail, and keeps it closed on narrowing again', async () => {
            const width = stubWidth(false)
            await renderShell(SIGNED_IN)
            fireEvent.click(screen.getByRole('button', { name: 'Open the rail' }))

            act(() => width.set(true))
            expect(screen.queryByRole('dialog', { name: 'Rail' })).toBeNull()
            expect(screen.getByRole('searchbox', { name: 'Search the journal' })).toBeDefined()

            act(() => width.set(false))
            expect(screen.queryByRole('dialog', { name: 'Rail' })).toBeNull()
        })
    })
})
