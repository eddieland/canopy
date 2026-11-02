import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { otherTab, otherTabClears } from '@/test-utils'

import { DEFAULT, parsePlanText } from './plan-text'

// The setting is read when the module loads, so each test loads a fresh copy.
function load() {
    vi.resetModules()
    return import('./plan-text')
}

describe('parsePlanText', () => {
    it("defaults to a document's own size when nothing is stored", () => {
        expect(parsePlanText(null)).toBe(DEFAULT)
        expect(DEFAULT).toBe('normal')
    })

    it('reads what was stored, and falls back on anything else', () => {
        expect(parsePlanText('tiny')).toBe('tiny')
        expect(parsePlanText('small')).toBe('small')
        expect(parsePlanText('large')).toBe('large')
        expect(parsePlanText('huge')).toBe(DEFAULT)
    })
})

describe('usePlanText', () => {
    beforeEach(() => localStorage.clear())

    it('changes the size, and keeps it', async () => {
        const planText = await load()
        const { result } = renderHook(() => planText.usePlanText())
        expect(result.current).toBe('normal')

        act(() => planText.setPlanText('large'))
        expect(result.current).toBe('large')
        expect(localStorage.getItem(planText.STORAGE_KEY)).toBe('large')
    })

    it("follows another tab's setting, and storage cleared", async () => {
        const planText = await load()
        const { result } = renderHook(() => planText.usePlanText())

        act(() => otherTab(planText.STORAGE_KEY, 'small'))
        expect(result.current).toBe('small')
        act(() => otherTabClears())
        expect(result.current).toBe('normal')
    })
})
