import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { breakStorage, otherTab, otherTabClears } from '@/test-utils'

import { parseOpen, withOpen } from './context-chart-open'

// The pages are read when the module loads, so each test loads a fresh copy.
function load() {
    vi.resetModules()
    return import('./context-chart-open')
}

describe('parseOpen', () => {
    it('reads the pages stored, and none when nothing is', () => {
        expect(parseOpen('["tick","run"]')).toEqual(['run', 'tick'])
        expect(parseOpen(null)).toEqual([])
    })

    it('keeps only the kinds it knows, and reads anything else as none', () => {
        expect(parseOpen('["run","ticket",2,null]')).toEqual(['run'])
        expect(parseOpen('{"run":true}')).toEqual([])
        expect(parseOpen('not json')).toEqual([])
    })
})

describe('withOpen', () => {
    it("opens or closes one kind's and leaves the others as they were", () => {
        expect(withOpen(['tick'], 'run', true)).toBe('["run","tick"]')
        expect(withOpen(['run', 'tick'], 'run', false)).toBe('["tick"]')
        expect(withOpen(['run'], 'run', true)).toBe('["run"]')
    })
})

describe('useContextChartOpen', () => {
    beforeEach(() => localStorage.clear())

    it("opens one kind's and closes it, keeps it, and leaves the others closed", async () => {
        const open = await load()
        const { result } = renderHook(() => [open.useContextChartOpen('run'), open.useContextChartOpen('tick')])
        expect(result.current).toEqual([false, false])

        act(() => open.setContextChartOpen('run', true))
        expect(result.current).toEqual([true, false])
        expect(localStorage.getItem(open.STORAGE_KEY)).toBe('["run"]')

        act(() => open.setContextChartOpen('run', false))
        expect(result.current).toEqual([false, false])
    })

    it("follows another tab's choices, one made before they were read, and storage cleared", async () => {
        const open = await load()
        localStorage.setItem(open.STORAGE_KEY, '["chore-run"]')
        const { result } = renderHook(() => open.useContextChartOpen('chore-run'))
        expect(result.current).toBe(true)

        act(() => otherTab(open.STORAGE_KEY, '[]'))
        expect(result.current).toBe(false)
        act(() => otherTab(open.STORAGE_KEY, '["chore-run"]'))
        act(() => otherTabClears())
        expect(result.current).toBe(false)
    })

    it('is closed where storage is unavailable, and still opens for this page', async () => {
        breakStorage()
        const open = await load()
        const { result } = renderHook(() => open.useContextChartOpen('tick'))
        expect(result.current).toBe(false)

        act(() => open.setContextChartOpen('tick', true))
        expect(result.current).toBe(true)
    })
})
