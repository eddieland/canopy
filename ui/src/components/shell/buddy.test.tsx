import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
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

// The tip Sprig's bubble shows, or null while it is hidden: a hidden bubble keeps its last tip, to hold its room.
function shown(tip: string) {
    const bubble = screen.getByTestId('buddy-tip')
    return bubble.classList.contains('invisible') ? null : within(bubble).queryByText(tip)
}

describe('Buddy', () => {
    it('opens on no tip, offers one about the page shown on a click on Sprig, the next on Another tip', async () => {
        await renderBuddy('/attention')
        expect(shown(tipFor('/attention', 0, NOW))).toBeNull()

        fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))
        expect(shown(tipFor('/attention', 1, NOW))).not.toBeNull()

        fireEvent.click(screen.getByRole('button', { name: 'Another tip' }))
        expect(shown(tipFor('/attention', 2, NOW))).not.toBeNull()
    })

    it('goes on from the last page load, rather than offering the same tips over', async () => {
        await renderBuddy('/attention')
        fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))
        fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))
        cleanup()

        await renderBuddy('/attention')
        expect(shown(tipFor('/attention', 2, NOW))).toBeNull()
        fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))
        expect(shown(tipFor('/attention', 3, NOW))).not.toBeNull()
    })

    it('keeps a tip to the page it was offered on, and offers the next about the page turned to', async () => {
        const router = await renderBuddy('/attention')
        fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))

        await act(() => router.navigate({ to: '/settings' }))
        expect(shown(tipFor('/attention', 1, NOW))).toBeNull()
        expect(shown(tipFor('/settings', 1, NOW))).toBeNull()

        fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))
        expect(shown(tipFor('/settings', 2, NOW))).not.toBeNull()
    })

    it('turns itself off, as Settings does, when told not to show tips again', async () => {
        await renderBuddy('/attention')
        fireEvent.click(screen.getByRole('button', { name: "Don't show me tips again" }))
        expect(localStorage.getItem(STORAGE_KEY)).toBe('off')
    })
})
