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

import { ANYWHERE, nextTip, RAVE, setCompanion, STORAGE_KEY, TIPS, tipsFor, VOICES } from '@/lib/buddy'
import { GHOST_ANYWHERE, GHOST_RAVE, GHOST_TIPS } from '@/lib/ghost'
import { setRave } from '@/lib/rave'

import { Buddy } from './buddy'

const NOW = Date.parse('2026-10-08T12:00:00Z')

beforeEach(() => {
    localStorage.clear()
    vi.useFakeTimers({ toFake: ['Date'], now: NOW })
})

afterEach(() => {
    cleanup()
    act(() => setRave('off'))
    act(() => setCompanion('sprig'))
    vi.useRealTimers()
    vi.unstubAllGlobals()
    localStorage.clear()
})

// A ResizeObserver that measures once, as the browser does when it starts observing: in happy-dom, which lays nothing
// out, Sprig's slot then has room for its bubble.
class MeasureOnce implements ResizeObserver {
    readonly #callback: ResizeObserverCallback

    constructor(callback: ResizeObserverCallback) {
        this.#callback = callback
    }

    observe(): void {
        this.#callback([], this)
    }

    disconnect(): void {}

    unobserve(): void {}
}

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
    const all = Object.values(VOICES)
        .flatMap(({ tips, anywhere, rave }) => [Object.values(tips).flat(), anywhere, rave])
        .flat()
    return all.find((tip) => within(bubble).queryByText(tip) !== null) ?? null
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
        const held = nextTip(tipsFor('/attention', false), '', () => 0.5)
        await renderBuddy('/attention')
        fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))
        expect(shown()).toBe(nextTip(tipsFor('/attention', false), held, () => 0.5))
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

    it("stands a jack-o'-lantern beside Sprig at Halloween, and nothing on an ordinary day", async () => {
        await renderBuddy('/attention')
        expect(screen.queryByTestId('buddy-season')).toBeNull()
        cleanup()

        vi.setSystemTime(new Date(2026, 9, 30, 12))
        await renderBuddy('/attention')
        expect(screen.getByTestId('buddy-season').dataset['season']).toBe('halloween')
    })

    describe("with the Ghost in Sprig's place", () => {
        it('goes by its own name and speaks in its own voice', async () => {
            act(() => setCompanion('ghost'))
            await renderBuddy('/attention')
            expect(screen.getByRole('complementary', { name: 'Ghost' })).toBeDefined()
            expect(screen.queryByRole('complementary', { name: 'Sprig' })).toBeNull()

            fireEvent.click(screen.getByRole('button', { name: 'Ask Ghost for a tip' }))
            expect([...GHOST_TIPS['/attention'], ...GHOST_ANYWHERE]).toContain(shown())
            expect(screen.getByTestId('ghost-body')).toBeDefined()
            expect(screen.queryByTestId('buddy-body')).toBeNull()
        })

        it("hides a tip Sprig offered, never showing it under the Ghost's name", async () => {
            await renderBuddy('/attention')
            fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))
            expect([...TIPS['/attention'], ...ANYWHERE]).toContain(shown())

            act(() => setCompanion('ghost'))
            expect(shown()).toBeNull()
            fireEvent.click(screen.getByRole('button', { name: 'Ask Ghost for a tip' }))
            expect([...GHOST_TIPS['/attention'], ...GHOST_ANYWHERE]).toContain(shown())
        })

        it('talks of the rave alone while the lights rave', async () => {
            act(() => setCompanion('ghost'))
            act(() => setRave('on'))
            await renderBuddy('/settings')
            fireEvent.click(screen.getByRole('button', { name: 'Ask Ghost for a tip' }))
            expect(GHOST_RAVE).toContain(shown())
        })
    })

    describe('at the lightswitch rave', () => {
        it('talks of nothing else, on any page', async () => {
            act(() => setRave('on'))
            await renderBuddy('/attention')
            fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))
            expect(RAVE).toContain(shown())
        })

        it('offers a tip about it as the lights go off, and hides it once they come back on', async () => {
            vi.stubGlobal('ResizeObserver', MeasureOnce)
            await renderBuddy('/settings')
            fireEvent.click(screen.getByRole('button', { name: 'Ask Sprig for a tip' }))
            expect(RAVE).not.toContain(shown())

            act(() => setRave('on'))
            expect(RAVE).toContain(shown())

            act(() => setRave('off'))
            expect(shown()).toBeNull()
        })

        it('says nothing unasked on a page that loads with the lights already raving', async () => {
            vi.stubGlobal('ResizeObserver', MeasureOnce)
            act(() => setRave('on'))
            await renderBuddy('/attention')
            expect(shown()).toBeNull()
        })
    })
})
