import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { breakStorage, otherTab, otherTabClears } from '@/test-utils'

import { DEFAULT_CLOCK, parseClock } from './clock'

// The setting is read when the module loads, so each test loads a fresh copy.
function load() {
    vi.resetModules()
    return import('./clock')
}

describe('parseClock', () => {
    it('defaults to a 24-hour clock without the zone when nothing is stored', () => {
        expect(parseClock(null)).toEqual(DEFAULT_CLOCK)
        expect(DEFAULT_CLOCK).toEqual({ hours: '24', zone: false })
    })

    it('reads what was stored, and falls back field by field on anything else', () => {
        expect(parseClock('{"hours":"12","zone":true}')).toEqual({ hours: '12', zone: true })
        expect(parseClock('{"hours":"13","zone":true}')).toEqual({ hours: '24', zone: true })
        expect(parseClock('{"hours":"12","zone":"yes"}')).toEqual({ hours: '12', zone: false })
        expect(parseClock('not json')).toEqual(DEFAULT_CLOCK)
        expect(parseClock('"12"')).toEqual(DEFAULT_CLOCK)
    })
})

describe('useClock', () => {
    beforeEach(() => localStorage.clear())

    it('changes the clock, and keeps it', async () => {
        const clock = await load()
        const { result } = renderHook(() => clock.useClock())
        expect(result.current).toEqual(DEFAULT_CLOCK)

        act(() => clock.setClock({ hours: '12' }))
        expect(result.current).toEqual({ hours: '12', zone: false })
        act(() => clock.setClock({ zone: true }))
        expect(result.current).toEqual({ hours: '12', zone: true })
        expect(clock.currentClock()).toEqual({ hours: '12', zone: true })
        expect(clock.parseClock(localStorage.getItem(clock.STORAGE_KEY))).toEqual({ hours: '12', zone: true })
    })

    it("follows another tab's setting, one made before it was read, and storage cleared", async () => {
        const clock = await load()
        localStorage.setItem(clock.STORAGE_KEY, '{"hours":"12","zone":false}')
        const { result } = renderHook(() => clock.useClock())
        expect(result.current).toEqual({ hours: '12', zone: false })

        act(() => otherTab(clock.STORAGE_KEY, '{"hours":"12","zone":true}'))
        expect(result.current).toEqual({ hours: '12', zone: true })
        act(() => otherTabClears())
        expect(result.current).toEqual(DEFAULT_CLOCK)
    })

    it('reads a 24-hour clock where storage is unavailable, and still changes for this page', async () => {
        breakStorage()
        const clock = await load()
        const { result } = renderHook(() => clock.useClock())
        expect(result.current).toEqual(DEFAULT_CLOCK)

        act(() => clock.setClock({ hours: '12' }))
        expect(result.current).toEqual({ hours: '12', zone: false })
    })
})
