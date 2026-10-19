import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { breakStorage, otherTab, otherTabClears } from '@/test-utils'

import { DEFAULTS, parseToastSettings, withState } from './toast-settings'

// The settings are read when the module loads, so each test loads a fresh copy.
function load() {
    vi.resetModules()
    return import('./toast-settings')
}

describe('parseToastSettings', () => {
    it('turns on no toast when nothing, or nothing it can read, is stored', () => {
        expect(DEFAULTS).toEqual({ tickets: [], reviews: [] })
        expect(parseToastSettings(null)).toEqual(DEFAULTS)
        expect(parseToastSettings('not json')).toEqual(DEFAULTS)
        expect(parseToastSettings('["ready"]')).toEqual(DEFAULTS)
        expect(parseToastSettings('{"tickets":"ready"}')).toEqual(DEFAULTS)
    })

    it("keeps each subject's known states, once each, in their order, and drops unknown subjects", () => {
        expect(
            parseToastSettings('{"tickets":["done","ci_red","ready","done"],"reviews":["failed","done"],"ships":[]}'),
        ).toEqual({ tickets: ['ready', 'done'], reviews: ['failed'] })
    })
})

describe('withState', () => {
    it("turns one subject's state on or off, keeping the order", () => {
        expect(withState({ tickets: ['done'], reviews: [] }, 'tickets', 'blocked', true)).toEqual({
            tickets: ['blocked', 'done'],
            reviews: [],
        })
        expect(withState({ tickets: ['blocked', 'done'], reviews: [] }, 'tickets', 'blocked', false)).toEqual({
            tickets: ['done'],
            reviews: [],
        })
        expect(withState({ tickets: [], reviews: [] }, 'tickets', 'ready', false)).toEqual({ tickets: [], reviews: [] })
        expect(withState({ tickets: ['done'], reviews: [] }, 'reviews', 'failed', true)).toEqual({
            tickets: ['done'],
            reviews: ['failed'],
        })
    })
})

describe('useToastSettings', () => {
    beforeEach(() => localStorage.clear())

    it('turns states on, and keeps them', async () => {
        const toasts = await load()
        const { result } = renderHook(() => toasts.useToastSettings())
        expect(result.current).toEqual({ tickets: [], reviews: [] })

        act(() => toasts.setToastSettings({ tickets: ['blocked', 'done'], reviews: [] }))
        expect(result.current).toEqual({ tickets: ['blocked', 'done'], reviews: [] })
        expect(localStorage.getItem(toasts.STORAGE_KEY)).toBe('{"tickets":["blocked","done"],"reviews":[]}')
    })

    it("follows another tab's settings, ones stored before it was read, and storage cleared", async () => {
        const toasts = await load()
        localStorage.setItem(toasts.STORAGE_KEY, '{"tickets":["ready"]}')
        const { result } = renderHook(() => toasts.useToastSettings())
        expect(result.current).toEqual({ tickets: ['ready'], reviews: [] })

        act(() => otherTab(toasts.STORAGE_KEY, '{"tickets":["split"]}'))
        expect(result.current).toEqual({ tickets: ['split'], reviews: [] })
        act(() => otherTabClears())
        expect(result.current).toEqual({ tickets: [], reviews: [] })
    })

    it('turns none on where storage is unavailable, and still changes for this page', async () => {
        breakStorage()
        const toasts = await load()
        const { result } = renderHook(() => toasts.useToastSettings())
        expect(result.current).toEqual({ tickets: [], reviews: [] })

        act(() => toasts.setToastSettings({ tickets: ['done'], reviews: [] }))
        expect(result.current).toEqual({ tickets: ['done'], reviews: [] })
    })
})
