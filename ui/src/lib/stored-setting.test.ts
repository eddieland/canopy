import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { breakStorage, otherTab, otherTabClears } from '@/test-utils'

import { storedSetting, useStoredSetting } from './stored-setting'

const KEY = 'canopy-test-setting'

// A list of words, stored as JSON, keeping only strings: none for anything else.
function words() {
    return storedSetting<string[]>({
        key: KEY,
        parse: (raw) => {
            try {
                const value: unknown = JSON.parse(raw ?? '[]')
                return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []
            } catch {
                return []
            }
        },
        serialize: JSON.stringify,
    })
}

describe('storedSetting', () => {
    beforeEach(() => localStorage.clear())

    it('reads what is stored, stores what is set, and applies it now', () => {
        localStorage.setItem(KEY, '["a"]')
        const setting = words()
        expect(setting.get()).toEqual(['a'])

        setting.set(['a', 'b'])
        expect(setting.get()).toEqual(['a', 'b'])
        expect(localStorage.getItem(KEY)).toBe('["a","b"]')
    })

    it('re-renders on a change from this tab or another, and on storage cleared', () => {
        const setting = words()
        const { result } = renderHook(() => useStoredSetting(setting))
        expect(result.current).toEqual([])

        act(() => setting.set(['a']))
        expect(result.current).toEqual(['a'])
        act(() => otherTab(KEY, '["b"]'))
        expect(result.current).toEqual(['b'])
        act(() => otherTab('canopy-another-key', '["c"]'))
        expect(result.current).toEqual(['b'])
        act(() => otherTabClears())
        expect(result.current).toEqual([])
    })

    it('catches a change made after it was read and before anything subscribed', () => {
        const setting = words()
        localStorage.setItem(KEY, '["late"]')
        const { result } = renderHook(() => useStoredSetting(setting))
        expect(result.current).toEqual(['late'])
    })

    it('tells no one of a value stored alike, keeping the one it had', () => {
        const setting = words()
        setting.set(['a'])
        const before = setting.get()
        const heard = vi.fn<() => void>()
        const stop = setting.subscribe(heard)

        setting.set(['a'])
        otherTab(KEY, '["a", 1]')
        expect(heard).not.toHaveBeenCalled()
        expect(setting.get()).toBe(before)

        setting.set(['b'])
        expect(heard).toHaveBeenCalledTimes(1)
        stop()
        setting.set(['c'])
        otherTab(KEY, '["d"]')
        expect(heard).toHaveBeenCalledTimes(1)
    })

    it('reads nothing where storage is unavailable, and still applies a change to this page', () => {
        breakStorage()
        const setting = words()
        const { result } = renderHook(() => useStoredSetting(setting))
        expect(result.current).toEqual([])

        act(() => setting.set(['a']))
        expect(result.current).toEqual(['a'])
    })
})
