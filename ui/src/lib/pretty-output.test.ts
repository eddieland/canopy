import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { breakStorage, otherTab, otherTabClears } from '@/test-utils'

import { MAX_KEPT, parsePretty, withPretty } from './pretty-output'

// The ticks are read when the module loads, so each test loads a fresh copy.
function load() {
    vi.resetModules()
    return import('./pretty-output')
}

describe('parsePretty', () => {
    it('reads the ticks stored, and nothing when nothing is', () => {
        expect(parsePretty('[2,7]')).toEqual([2, 7])
        expect(parsePretty(null)).toEqual([])
    })

    it('keeps only whole positive numbers, and reads anything else as none', () => {
        expect(parsePretty('[2,"3",-1,0,1.5,null,9]')).toEqual([2, 9])
        expect(parsePretty('{"2":true}')).toEqual([])
        expect(parsePretty('not json')).toEqual([])
    })
})

describe('withPretty', () => {
    it("turns one tick's on or off and leaves the others as they were", () => {
        expect(withPretty([2], 7, true)).toEqual([2, 7])
        expect(withPretty([2, 7], 2, false)).toEqual([7])
        expect(withPretty([2], 9, false)).toEqual([2])
    })

    it('moves a tick turned on again to the end, and drops the oldest past the limit', () => {
        expect(withPretty([2, 7], 2, true)).toEqual([7, 2])
        const full = Array.from({ length: MAX_KEPT }, (_, i) => i + 1)
        const kept = withPretty(full, 1000, true)
        expect(kept).toHaveLength(MAX_KEPT)
        expect(kept[0]).toBe(2)
        expect(kept.at(-1)).toBe(1000)
    })
})

describe('usePrettyOutput', () => {
    beforeEach(() => localStorage.clear())

    it("turns one tick's on and off, keeps it, and leaves the others compact", async () => {
        const pretty = await load()
        const { result } = renderHook(() => [pretty.usePrettyOutput(2), pretty.usePrettyOutput(7)])
        expect(result.current).toEqual([false, false])

        act(() => pretty.setPrettyOutput(2, true))
        expect(result.current).toEqual([true, false])
        expect(localStorage.getItem(pretty.STORAGE_KEY)).toBe('[2]')

        act(() => pretty.setPrettyOutput(2, false))
        expect(result.current).toEqual([false, false])
    })

    it("follows another tab's choices, one made before they were read, and storage cleared", async () => {
        const pretty = await load()
        localStorage.setItem(pretty.STORAGE_KEY, '[7]')
        const { result } = renderHook(() => pretty.usePrettyOutput(7))
        expect(result.current).toBe(true)

        act(() => otherTab(pretty.STORAGE_KEY, '[2,7]'))
        expect(result.current).toBe(true)
        act(() => otherTab(pretty.STORAGE_KEY, '[2]'))
        expect(result.current).toBe(false)
        act(() => otherTab(pretty.STORAGE_KEY, '[7]'))
        act(() => otherTabClears())
        expect(result.current).toBe(false)
    })

    it('is compact where storage is unavailable, and still turns pretty for this page', async () => {
        breakStorage()
        const pretty = await load()
        const { result } = renderHook(() => pretty.usePrettyOutput(7))
        expect(result.current).toBe(false)

        act(() => pretty.setPrettyOutput(7, true))
        expect(result.current).toBe(true)
    })
})
