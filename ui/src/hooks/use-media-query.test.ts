import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useMediaQuery } from './use-media-query'

// Stubs matchMedia so `query` matches when `matches`, and lets a test change that later, as a resize would.
function stubQuery(query: string, matches: boolean): { set: (matches: boolean) => void; listening: () => number } {
    let now = matches
    const listeners = new Set<() => void>()
    vi.stubGlobal(
        'matchMedia',
        vi.fn((asked: string) => ({
            get matches() {
                return asked === query && now
            },
            media: asked,
            addEventListener: (_: string, listener: () => void) => listeners.add(listener),
            removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
        })),
    )
    return {
        set(next) {
            now = next
            for (const listener of listeners) {
                listener()
            }
        },
        listening: () => listeners.size,
    }
}

describe('useMediaQuery', () => {
    it('follows the query as it starts and stops matching', () => {
        const wide = stubQuery('(min-width: 64rem)', false)
        const { result } = renderHook(() => useMediaQuery('(min-width: 64rem)'))
        expect(result.current).toBe(false)

        act(() => wide.set(true))
        expect(result.current).toBe(true)
        act(() => wide.set(false))
        expect(result.current).toBe(false)
    })

    it('matches only the query it asks', () => {
        stubQuery('(min-width: 64rem)', true)
        const { result } = renderHook(() => useMediaQuery('(prefers-reduced-motion: reduce)'))
        expect(result.current).toBe(false)
    })

    it('stops listening when it unmounts', () => {
        const wide = stubQuery('(min-width: 64rem)', true)
        const { unmount } = renderHook(() => useMediaQuery('(min-width: 64rem)'))
        expect(wide.listening()).toBe(1)

        unmount()
        expect(wide.listening()).toBe(0)
    })
})
