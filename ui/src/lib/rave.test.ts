import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { breakStorage, otherTab, otherTabClears } from '@/test-utils'

import { DEFAULT, parseRave } from './rave'

// The setting is read when the module loads, so each test loads a fresh copy.
function load() {
    vi.resetModules()
    return import('./rave')
}

describe('parseRave', () => {
    it('is off when nothing is stored', () => {
        expect(parseRave(null)).toBe(DEFAULT)
        expect(DEFAULT).toBe('off')
    })

    it('reads what was stored, and falls back on anything else', () => {
        expect(parseRave('on')).toBe('on')
        expect(parseRave('off')).toBe('off')
        expect(parseRave('everybody')).toBe(DEFAULT)
    })
})

describe('useRave', () => {
    beforeEach(() => localStorage.clear())

    it('turns on with the switch, keeps it, and turns off again', async () => {
        const rave = await load()
        const { result } = renderHook(() => rave.useRave())
        expect(result.current).toBe('off')

        act(() => rave.setRave('on'))
        expect(result.current).toBe('on')
        expect(localStorage.getItem(rave.STORAGE_KEY)).toBe('on')

        act(() => rave.setRave('off'))
        expect(result.current).toBe('off')
        expect(localStorage.getItem(rave.STORAGE_KEY)).toBe('off')
    })

    it("follows another tab's switch, one flipped before it was read, and storage cleared", async () => {
        const rave = await load()
        localStorage.setItem(rave.STORAGE_KEY, 'on')
        const { result } = renderHook(() => rave.useRave())
        expect(result.current).toBe('on')

        act(() => otherTab(rave.STORAGE_KEY, 'off'))
        expect(result.current).toBe('off')
        act(() => otherTab(rave.STORAGE_KEY, 'on'))
        expect(result.current).toBe('on')
        act(() => otherTabClears())
        expect(result.current).toBe('off')
    })

    it('is off where storage is unavailable, and still turns on for this page', async () => {
        breakStorage()
        const rave = await load()
        const { result } = renderHook(() => rave.useRave())
        expect(result.current).toBe('off')

        act(() => rave.setRave('on'))
        expect(result.current).toBe('on')
    })
})

describe('onRaveStart', () => {
    beforeEach(() => localStorage.clear())

    it('hears each start, from this tab or another, never a rave already on or one ending', async () => {
        localStorage.setItem('canopy-rave', 'on')
        const rave = await load()
        const heard = vi.fn<() => void>()
        const stop = rave.onRaveStart(heard)
        expect(heard).not.toHaveBeenCalled()

        rave.setRave('off')
        expect(heard).not.toHaveBeenCalled()
        rave.setRave('on')
        expect(heard).toHaveBeenCalledTimes(1)
        otherTab(rave.STORAGE_KEY, 'off')
        otherTab(rave.STORAGE_KEY, 'on')
        expect(heard).toHaveBeenCalledTimes(2)

        stop()
        rave.setRave('off')
        rave.setRave('on')
        expect(heard).toHaveBeenCalledTimes(2)
    })
})
