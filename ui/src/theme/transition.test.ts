import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'

// The store reads storage and the system theme when it loads, so each test loads a fresh copy of both.
function load({ reducedMotion = false } = {}) {
    vi.stubGlobal('matchMedia', (query: string) => ({
        matches: query === REDUCED_MOTION && reducedMotion,
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
    }))
    vi.resetModules()
    return import('./transition')
}

// A button 20 by 10 pixels whose top-left corner is at (`left`, `top`): by default, its center is at (110, 55).
function button(left = 100, top = 50): HTMLElement {
    const element = document.createElement('button')
    vi.spyOn(element, 'getBoundingClientRect').mockReturnValue(new DOMRect(left, top, 20, 10))
    return element
}

// The View Transitions API, which happy-dom does not have: it runs the update at once, then settles `ready`.
function stubViewTransitions(ready: Promise<void>) {
    const start = vi.fn<(update: () => void) => ViewTransition>((update) => {
        update()
        return { ready, finished: ready } as ViewTransition
    })
    Object.defineProperty(document, 'startViewTransition', { configurable: true, value: start })
    return start
}

beforeEach(() => {
    localStorage.clear()
    document.documentElement.className = ''
})

afterEach(() => {
    Reflect.deleteProperty(document, 'startViewTransition')
})

describe('switchTheme', () => {
    it('switches at once where the browser has no view transitions', async () => {
        const { switchTheme } = await load()
        switchTheme('dark', button())
        expect(document.documentElement.classList.contains('dark')).toBe(true)
    })

    it('switches at once, with no transition, under reduced motion or with nothing to grow from', async () => {
        const start = stubViewTransitions(Promise.resolve())
        const { switchTheme } = await load({ reducedMotion: true })
        switchTheme('dark', button())
        expect(document.documentElement.classList.contains('dark')).toBe(true)

        const again = await load()
        again.switchTheme('light', null)
        expect(document.documentElement.classList.contains('dark')).toBe(false)
        expect(start).not.toHaveBeenCalled()
    })

    it("switches in a transition, revealed by a circle from the button's center to the farthest corner", async () => {
        const start = stubViewTransitions(Promise.resolve())
        const animate = vi.spyOn(document.documentElement, 'animate')
        const { switchTheme } = await load()

        switchTheme('dark', button())
        expect(start).toHaveBeenCalledTimes(1)
        expect(document.documentElement.classList.contains('dark')).toBe(true)

        await vi.waitFor(() => expect(animate).toHaveBeenCalledTimes(1))
        const radius = Math.hypot(window.innerWidth - 110, window.innerHeight - 55)
        expect(animate).toHaveBeenCalledWith(
            { clipPath: ['circle(0px at 110px 55px)', `circle(${radius}px at 110px 55px)`] },
            expect.objectContaining({ pseudoElement: '::view-transition-new(root)' }),
        )

        // From near the bottom-right, the farthest corner is the top-left.
        switchTheme('light', button(900, 700))
        await vi.waitFor(() => expect(animate).toHaveBeenCalledTimes(2))
        expect(animate).toHaveBeenLastCalledWith(
            { clipPath: ['circle(0px at 910px 705px)', `circle(${Math.hypot(910, 705)}px at 910px 705px)`] },
            expect.anything(),
        )
    })

    it('keeps the new theme when the browser skips the transition', async () => {
        stubViewTransitions(Promise.reject(new DOMException('skipped', 'AbortError')))
        const animate = vi.spyOn(document.documentElement, 'animate')
        const { switchTheme } = await load()

        switchTheme('dark', button())
        await Promise.resolve()
        expect(document.documentElement.classList.contains('dark')).toBe(true)
        expect(animate).not.toHaveBeenCalled()
    })
})

describe('switchPalette', () => {
    it('reveals a palette for the theme shown, and picks one for the other theme at once', async () => {
        const start = stubViewTransitions(Promise.resolve())
        // The stubbed system is light, and nothing is stored, so the page shows light.
        const { switchPalette } = await load()

        const atOnce = switchPalette('dark', 'grey', button())
        expect(document.documentElement.dataset.darkPalette).toBe('grey')
        expect(start).not.toHaveBeenCalled()
        await atOnce

        const revealed = switchPalette('light', 'solarized', button())
        expect(document.documentElement.dataset.lightPalette).toBe('solarized')
        expect(start).toHaveBeenCalledTimes(1)
        await revealed
    })

    it('starts no reveal for the palette the theme already wears', async () => {
        const start = stubViewTransitions(Promise.resolve())
        const { switchPalette } = await load()

        await switchPalette('light', 'lavender', button())
        expect(start).not.toHaveBeenCalled()
        expect(localStorage).toHaveLength(0)
    })

    it('settles once the reveal is over, not before', async () => {
        let end: (() => void) | undefined
        const over = new Promise<void>((resolve) => {
            end = resolve
        })
        stubViewTransitions(over)
        const { switchPalette } = await load()
        let settled = false

        const done = switchPalette('light', 'sage', button()).then(() => {
            settled = true
            return settled
        })
        await Promise.resolve()
        expect(document.documentElement.dataset.lightPalette).toBe('sage')
        expect(settled).toBe(false)

        end?.()
        await done
        expect(settled).toBe(true)
    })
})
