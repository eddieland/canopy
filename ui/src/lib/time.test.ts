import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { age, endStamp, lasted, stamp, useNow } from './time'

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

describe('endStamp', () => {
    it('is the local time alone when it ended the day it started, else the whole stamp', () => {
        // Noon local, so 29 minutes on is the same local day and 26 hours on is not, in any time zone.
        const started = new Date(2026, 9, 8, 12, 0).toISOString()
        const sameDay = new Date(2026, 9, 8, 12, 29).toISOString()
        expect(endStamp(started, sameDay)).toBe('12:29')
        const nextDay = new Date(2026, 9, 9, 14, 5).toISOString()
        expect(endStamp(started, nextDay)).toBe(stamp(nextDay))
    })
})

describe('lasted', () => {
    it('says how long something ran in the largest whole unit, as an age does', () => {
        expect(lasted('2026-10-08T06:30:00Z', '2026-10-08T06:59:30Z')).toBe('29m')
        expect(lasted('2026-10-08T06:30:00Z', '2026-10-08T06:30:40Z')).toBe('40s')
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
