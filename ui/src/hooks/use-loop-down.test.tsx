import { act, cleanup, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BAND_MS, OFFLINE_MS, StreamContext, useLoopDown } from './use-loop-down'

beforeEach(() => {
    vi.useFakeTimers()
})

afterEach(() => {
    cleanup()
    vi.useRealTimers()
})

function loopDown(downSince: number | null) {
    let since = downSince
    const wrapper = ({ children }: { children: ReactNode }) => (
        <StreamContext value={{ status: since === null ? 'open' : 'reconnecting', downSince: since }}>
            {children}
        </StreamContext>
    )
    const hook = renderHook(() => useLoopDown(), { wrapper })
    return {
        ...hook,
        reopen: () => {
            since = null
            hook.rerender()
        },
    }
}

describe('useLoopDown', () => {
    it('is up while the stream is', () => {
        const { result } = loopDown(null)
        expect(result.current).toEqual({ since: null, offline: false, band: false })
    })

    it('goes offline after the first retry, then calls for the band, and is up again the moment it opens', () => {
        const since = Date.now()
        const { result, reopen } = loopDown(since)
        expect(result.current).toEqual({ since, offline: false, band: false })
        act(() => {
            vi.advanceTimersByTime(OFFLINE_MS)
        })
        expect(result.current).toEqual({ since, offline: true, band: false })
        act(() => {
            vi.advanceTimersByTime(BAND_MS - OFFLINE_MS)
        })
        expect(result.current).toEqual({ since, offline: true, band: true })

        reopen()
        expect(result.current).toEqual({ since: null, offline: false, band: false })
    })

    it('counts from the drop, so a page opened on a stream long down shows it at once', () => {
        const { result } = loopDown(Date.now() - 60_000)
        act(() => {
            vi.advanceTimersByTime(0)
        })
        expect(result.current.band).toBe(true)
    })
})
