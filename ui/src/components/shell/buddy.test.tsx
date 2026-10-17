import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import {
    createMemoryHistory,
    createRootRoute,
    createRoute,
    createRouter,
    Outlet,
    RouterProvider,
} from '@tanstack/react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { STORAGE_KEY, tipFor } from '@/lib/buddy'

import { Buddy } from './buddy'

const NOW = Date.parse('2026-10-08T12:00:00Z')

beforeEach(() => {
    localStorage.clear()
    vi.useFakeTimers({ toFake: ['Date'], now: NOW })
})

afterEach(() => {
    cleanup()
    vi.useRealTimers()
    localStorage.clear()
})

// Sprig beside two pages whose route ids are views with tips of their own, as the rail holds it on every page.
async function renderBuddy(at: '/attention' | '/settings') {
    const root = createRootRoute({
        component: () => (
            <>
                <Buddy />
                <Outlet />
            </>
        ),
    })
    const router = createRouter({
        routeTree: root.addChildren([
            createRoute({ getParentRoute: () => root, path: '/attention' }),
            createRoute({ getParentRoute: () => root, path: '/settings' }),
        ]),
        history: createMemoryHistory({ initialEntries: [at] }),
    })
    await router.load()
    render(<RouterProvider router={router} />)
    return router
}

// The tip Sprig's bubble says.
function said(tip: string) {
    return screen.queryByText(tip)
}

describe('Buddy', () => {
    it('opens on a tip about the page shown, and offers the next on Another tip or a click on Sprig', async () => {
        await renderBuddy('/attention')
        expect(said(tipFor('/attention', 0, NOW))).not.toBeNull()

        fireEvent.click(screen.getByRole('button', { name: 'Another tip' }))
        expect(said(tipFor('/attention', 1, NOW))).not.toBeNull()

        fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))
        expect(said(tipFor('/attention', 2, NOW))).not.toBeNull()
    })

    it("starts a new page at that page's own first tip", async () => {
        const router = await renderBuddy('/attention')
        fireEvent.click(screen.getByRole('button', { name: 'Another tip' }))

        await act(() => router.navigate({ to: '/settings' }))
        expect(said(tipFor('/settings', 0, NOW))).not.toBeNull()
    })

    it('turns itself off, as Settings does, when told not to show tips again', async () => {
        await renderBuddy('/attention')
        fireEvent.click(screen.getByRole('button', { name: "Don't show me tips again" }))
        expect(localStorage.getItem(STORAGE_KEY)).toBe('off')
    })
})
