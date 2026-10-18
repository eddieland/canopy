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

import { ANYWHERE, nextTip, STORAGE_KEY, TIPS } from '@/lib/buddy'

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
function shown(): string | null {
    const bubble = screen.getByTestId('buddy-tip')
    if (bubble.classList.contains('invisible')) {
        return null
    }
    return [...Object.values(TIPS).flat(), ...ANYWHERE].find((tip) => within(bubble).queryByText(tip) !== null) ?? null
}

describe('Buddy', () => {
    it('opens on no tip, offers one about the page shown on a click on Sprig, a new one on Another tip', async () => {
        await renderBuddy('/attention')
        expect(shown()).toBeNull()

        fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))
        const first = shown()
        expect([...TIPS['/attention'], ...ANYWHERE]).toContain(first)

        fireEvent.click(screen.getByRole('button', { name: 'Another tip' }))
        expect(shown()).not.toBeNull()
        expect(shown()).not.toBe(first)
    })

    it('picks each tip at random, never the one just offered', async () => {
        vi.spyOn(Math, 'random').mockReturnValue(0.5)
        // The pick that holds the bubble's room at load, then the one a click offers, which is never it.
        const held = nextTip('/attention', '', () => 0.5)
        await renderBuddy('/attention')
        fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))
        expect(shown()).toBe(nextTip('/attention', held, () => 0.5))
        expect(shown()).not.toBe(held)
    })

    it('keeps a tip to the page it was offered on, and offers a new one about the page turned to', async () => {
        const router = await renderBuddy('/attention')
        fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))
        const first = shown()

        await act(() => router.navigate({ to: '/settings' }))
        expect(shown()).toBeNull()

        fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))
        expect([...TIPS['/settings'], ...ANYWHERE]).toContain(shown())
        expect(shown()).not.toBe(first)
    })

    it('turns itself off, as Settings does, when told not to show tips again', async () => {
        await renderBuddy('/attention')
        fireEvent.click(screen.getByRole('button', { name: "Don't show me tips again" }))
        expect(localStorage.getItem(STORAGE_KEY)).toBe('off')
    })
})
