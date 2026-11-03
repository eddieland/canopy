import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useLeavingRows } from './use-leaving-rows'

interface Item {
    id: string
}

const a: Item = { id: 'a' }
const b: Item = { id: 'b' }
const c: Item = { id: 'c' }

// The list as the query holds it: undefined until it is read.
function render(list: Item[] | undefined) {
    return renderHook((data: Item[] | undefined) => useLeavingRows(data, data), { initialProps: list })
}

function leaveTime() {
    act(() => {
        vi.advanceTimersByTime(700)
    })
}

function stubReducedMotion() {
    vi.stubGlobal('matchMedia', (query: string) => ({
        matches: query === '(prefers-reduced-motion: reduce)',
        media: query,
        addEventListener: vi.fn<() => void>(),
        removeEventListener: vi.fn<() => void>(),
    }))
}

describe('useLeavingRows', () => {
    beforeEach(() => {
        vi.useFakeTimers()
    })

    afterEach(() => {
        vi.useRealTimers()
        vi.unstubAllGlobals()
    })

    it('holds the last row through its exit, then lets the all clear in as watched', () => {
        const { result, rerender } = render([a])

        rerender([])
        expect(result.current.rows).toEqual([{ item: a, leaving: true }])
        expect(result.current.clearing).toBe(true)

        leaveTime()
        expect(result.current.rows).toEqual([])
        expect(result.current.clearing).toBe(false)
        expect(result.current.cleared).toBe(true)
    })

    it('plays nothing on a list that opens empty', () => {
        const { result } = render([])
        expect(result.current).toEqual({ rows: [], clearing: false, cleared: false })
    })

    it('plays nothing on a list read empty after the page opened', () => {
        const { result, rerender } = render(undefined)
        rerender([])
        expect(result.current).toEqual({ rows: [], clearing: false, cleared: false })
    })

    it('never holds the all clear back under reduced motion, where the exit is not shown', () => {
        stubReducedMotion()
        const { result, rerender } = render([a])
        rerender([])
        expect(result.current.clearing).toBe(false)
    })

    it('does not start the exit over when the empty list arrives again', () => {
        const { result, rerender } = render([a])
        rerender([])
        act(() => {
            vi.advanceTimersByTime(400)
        })
        rerender([])
        act(() => {
            vi.advanceTimersByTime(300)
        })
        expect(result.current.rows).toEqual([])
    })

    it('stays clear once settled, whatever list of none arrives next', () => {
        const { result, rerender } = render([a])
        rerender([])
        leaveTime()
        rerender([])
        expect(result.current).toEqual({ rows: [], clearing: false, cleared: true })
    })

    it('stops clearing when an item arrives during the exit, and keeps the row that still leaves', () => {
        const { result, rerender } = render([a])
        rerender([])
        rerender([b])
        expect(result.current.clearing).toBe(false)
        expect(result.current.rows).toEqual([
            { item: a, leaving: true },
            { item: b, leaving: false },
        ])

        leaveTime()
        expect(result.current.rows).toEqual([{ item: b, leaving: false }])
    })

    it('lets the first row to leave go off with a flash', () => {
        const { result, rerender } = render([a, b])
        rerender([b])
        expect(result.current.burst).toBe('a')
    })

    it('flashes for one row of a burst of clears, not each', () => {
        const { result, rerender } = render([a, b, c])
        rerender([c])
        expect(result.current.burst).toBe('a')
        act(() => {
            vi.advanceTimersByTime(300)
        })
        rerender([])
        expect(result.current.burst).toBe('a')
    })

    it('flashes again only once the list has rested', () => {
        const { result, rerender } = render([a, b, c])
        rerender([b, c])
        act(() => {
            vi.advanceTimersByTime(699)
        })
        rerender([c])
        expect(result.current.burst).toBe('a')
        // The wait starts over with each row that leaves, so the slot frees a full exit after the last.
        act(() => {
            vi.advanceTimersByTime(699)
        })
        expect(result.current.burst).toBe('a')
        leaveTime()
        expect(result.current.burst).toBeUndefined()
        rerender([])
        expect(result.current.burst).toBe('c')
    })

    it('keeps the flash spent when its item comes back, so a second cannot follow at once', () => {
        const { result, rerender } = render([a, b])
        rerender([b])
        rerender([a, b])
        rerender([a])
        expect(result.current.burst).toBe('a')
        expect(result.current.rows).toEqual([
            { item: a, leaving: false },
            { item: b, leaving: true },
        ])
        leaveTime()
        expect(result.current.burst).toBeUndefined()
    })

    it('flashes nothing under reduced motion', () => {
        stubReducedMotion()
        const { result, rerender } = render([a, b])
        rerender([b])
        expect(result.current.burst).toBeUndefined()
    })

    it('does not clear while items are still listed', () => {
        const { result, rerender } = render([a, b])
        rerender([b])
        expect(result.current.clearing).toBe(false)
        leaveTime()
        expect(result.current).toEqual({ rows: [{ item: b, leaving: false }], clearing: false, cleared: false })
    })
})
