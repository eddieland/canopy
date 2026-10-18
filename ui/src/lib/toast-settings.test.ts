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
        expect(DEFAULTS).toEqual({ tickets: [] })
        expect(parseToastSettings(null)).toEqual(DEFAULTS)
        expect(parseToastSettings('not json')).toEqual(DEFAULTS)
        expect(parseToastSettings('["ready"]')).toEqual(DEFAULTS)
        expect(parseToastSettings('{"tickets":"ready"}')).toEqual(DEFAULTS)
    })

    it("keeps each subject's known states, once each, in their order, and drops unknown subjects", () => {
        expect(parseToastSettings('{"tickets":["done","ci_red","ready","done"],"spaceships":["ready"]}')).toEqual({
            tickets: ['ready', 'done'],
        })
    })
})

describe('withState', () => {
    it("turns one subject's state on or off, keeping the order", () => {
        expect(withState({ tickets: ['done'] }, 'tickets', 'blocked', true)).toEqual({ tickets: ['blocked', 'done'] })
        expect(withState({ tickets: ['blocked', 'done'] }, 'tickets', 'blocked', false)).toEqual({ tickets: ['done'] })
        expect(withState({ tickets: [] }, 'tickets', 'ready', false)).toEqual({ tickets: [] })
    })
})

describe('useToastSettings', () => {
    beforeEach(() => localStorage.clear())

    it('turns states on, and keeps them', async () => {
        const toasts = await load()
        const { result } = renderHook(() => toasts.useToastSettings())
        expect(result.current).toEqual({ tickets: [] })

        act(() => toasts.setToastSettings({ tickets: ['blocked', 'done'] }))
        expect(result.current).toEqual({ tickets: ['blocked', 'done'] })
        expect(localStorage.getItem(toasts.STORAGE_KEY)).toBe('{"tickets":["blocked","done"]}')
    })

    it("follows another tab's settings, ones stored before it was read, and storage cleared", async () => {
        const toasts = await load()
        localStorage.setItem(toasts.STORAGE_KEY, '{"tickets":["ready"]}')
        const { result } = renderHook(() => toasts.useToastSettings())
        expect(result.current).toEqual({ tickets: ['ready'] })

        act(() => otherTab(toasts.STORAGE_KEY, '{"tickets":["split"]}'))
        expect(result.current).toEqual({ tickets: ['split'] })
        act(() => otherTabClears())
        expect(result.current).toEqual({ tickets: [] })
    })

    it('turns none on where storage is unavailable, and still changes for this page', async () => {
        breakStorage()
        const toasts = await load()
        const { result } = renderHook(() => toasts.useToastSettings())
        expect(result.current).toEqual({ tickets: [] })

        act(() => toasts.setToastSettings({ tickets: ['done'] }))
        expect(result.current).toEqual({ tickets: ['done'] })
    })
})
