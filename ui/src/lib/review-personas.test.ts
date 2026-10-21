import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { PersonaList } from '@/api/types'
import { breakStorage, otherTab, otherTabClears } from '@/test-utils'

import { MAX_PERSONAS, parseReviewPersonas, usablePersonas } from './review-personas'

// The setting is read when the module loads, so each test loads a fresh copy.
function load() {
    vi.resetModules()
    return import('./review-personas')
}

const PERSONAS: PersonaList = {
    reviewer: 'canopy',
    personas: [
        { name: 'canopy', yours: false, defaults: ['worker', 'planner', 'reviewer'], error: null },
        { name: 'gone', yours: true, defaults: [], error: 'persona gone is past 4096 bytes' },
        { name: 'skeptic', yours: false, defaults: [], error: null },
    ],
}

describe('parseReviewPersonas', () => {
    it('prefers none when nothing is stored, or anything but a list', () => {
        expect(parseReviewPersonas(null)).toEqual([])
        expect(parseReviewPersonas('not json')).toEqual([])
        expect(parseReviewPersonas('"skeptic"')).toEqual([])
        expect(parseReviewPersonas('{"skeptic":true}')).toEqual([])
    })

    it('reads each name once, in order, and no more than a request may name', () => {
        expect(parseReviewPersonas('["skeptic","canopy"]')).toEqual(['skeptic', 'canopy'])
        expect(parseReviewPersonas('["skeptic",3,"","skeptic",null,"canopy"]')).toEqual(['skeptic', 'canopy'])
        const names = Array.from({ length: MAX_PERSONAS + 2 }, (_, i) => `p${i}`)
        expect(parseReviewPersonas(JSON.stringify(names))).toEqual(names.slice(0, MAX_PERSONAS))
    })
})

describe('usablePersonas', () => {
    it('keeps the preferred personas canopy would run, in the order preferred', () => {
        expect(usablePersonas(['skeptic', 'canopy'], PERSONAS)).toEqual(['skeptic', 'canopy'])
        // One refused, and one since removed, are left out.
        expect(usablePersonas(['gone', 'skeptic', 'removed'], PERSONAS)).toEqual(['skeptic'])
    })

    it('keeps them all while the list is still being read', () => {
        expect(usablePersonas(['skeptic', 'removed'], undefined)).toEqual(['skeptic', 'removed'])
    })
})

describe('useReviewPersonas', () => {
    beforeEach(() => localStorage.clear())

    it('changes the preferred personas, and keeps them', async () => {
        const setting = await load()
        const { result } = renderHook(() => setting.useReviewPersonas())
        expect(result.current).toEqual([])

        act(() => setting.setReviewPersonas(['skeptic', 'canopy']))
        expect(result.current).toEqual(['skeptic', 'canopy'])
        expect(localStorage.getItem(setting.STORAGE_KEY)).toBe('["skeptic","canopy"]')
        act(() => setting.setReviewPersonas([]))
        expect(result.current).toEqual([])
    })

    it("follows another tab's choice, and storage cleared", async () => {
        const setting = await load()
        const { result } = renderHook(() => setting.useReviewPersonas())
        act(() => otherTab(setting.STORAGE_KEY, '["skeptic"]'))
        expect(result.current).toEqual(['skeptic'])
        act(() => otherTabClears())
        expect(result.current).toEqual([])
    })

    it('prefers none where storage is unavailable, and still changes for this page', async () => {
        breakStorage()
        const setting = await load()
        const { result } = renderHook(() => setting.useReviewPersonas())
        expect(result.current).toEqual([])
        act(() => setting.setReviewPersonas(['skeptic']))
        expect(result.current).toEqual(['skeptic'])
    })
})
