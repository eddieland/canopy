import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { age, stamp, useNow } from './time'

describe('age', () => {
    const now = Date.parse('2026-10-08T12:30:00Z')

    it('names the largest whole unit, as the CLI does', () => {
        expect(age('2026-10-08T12:29:20Z', now)).toBe('40s')
        expect(age('2026-10-08T12:25:00Z', now)).toBe('5m')
        expect(age('2026-10-08T10:00:00Z', now)).toBe('2h')
        expect(age('2026-10-05T12:00:00Z', now)).toBe('3d')
    })

    it('never goes negative for a time a little ahead of the clock', () => {
        expect(age('2026-10-08T12:31:00Z', now)).toBe('0s')
    })
})

describe('stamp', () => {
    it('is the local month, day, and 24-hour time, without the year or seconds', () => {
        const iso = '2026-10-08T10:30:45Z'
        const local = new Date(iso)
        const hh = String(local.getHours()).padStart(2, '0')
        const mm = String(local.getMinutes()).padStart(2, '0')
        expect(stamp(iso)).toMatch(new RegExp(`^\\S+ ${local.getDate()} ${hh}:${mm}$`, 'u'))
    })
})

describe('useNow', () => {
    afterEach(() => {
        vi.useRealTimers()
    })

    it('reads the time when first read, and again every second', () => {
        vi.useFakeTimers({ now: Date.parse('2026-10-08T12:00:00Z') })
        const { result, unmount } = renderHook(() => useNow())
        expect(result.current).toBe(Date.parse('2026-10-08T12:00:00Z'))

        act(() => {
            vi.advanceTimersByTime(999)
        })
        expect(result.current).toBe(Date.parse('2026-10-08T12:00:00Z'))
        act(() => {
            vi.advanceTimersByTime(1)
        })
        expect(result.current).toBe(Date.parse('2026-10-08T12:00:01Z'))
        unmount()
    })

    it('runs one clock for every reader, and stops it once none is left', () => {
        vi.useFakeTimers({ now: Date.parse('2026-10-08T12:00:00Z') })
        const first = renderHook(() => useNow())
        const second = renderHook(() => useNow())
        expect(vi.getTimerCount()).toBe(1)

        act(() => {
            vi.advanceTimersByTime(3000)
        })
        expect(first.result.current).toBe(second.result.current)

        first.unmount()
        expect(vi.getTimerCount()).toBe(1)
        second.unmount()
        expect(vi.getTimerCount()).toBe(0)
    })

    it('starts again from the time it is read, not the time it stopped', () => {
        vi.useFakeTimers({ now: Date.parse('2026-10-08T12:00:00Z') })
        renderHook(() => useNow()).unmount()

        vi.setSystemTime(Date.parse('2026-10-08T13:00:00Z'))
        const { result, unmount } = renderHook(() => useNow())
        expect(result.current).toBe(Date.parse('2026-10-08T13:00:00Z'))
        unmount()
    })
})
