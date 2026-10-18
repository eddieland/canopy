import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { mockTickets } from '@/api/mocks'
import type { TicketSummary } from '@/api/types'
import { breakStorage, otherTab, otherTabClears } from '@/test-utils'

import { parseStates, TICKET_TOAST_STATES, ticketToasts, withState } from './ticket-toasts'

// The settings are read when the module loads, so each test loads a fresh copy.
function load() {
    vi.resetModules()
    return import('./ticket-toasts')
}

function ticket(fields: Partial<TicketSummary>): TicketSummary {
    const [base] = mockTickets
    if (!base) {
        throw new Error('no mock ticket')
    }
    return { ...base, ...fields }
}

describe('parseStates', () => {
    it('turns on none when nothing, or nothing it can read, is stored', () => {
        expect(parseStates(null)).toEqual([])
        expect(parseStates('not json')).toEqual([])
        expect(parseStates('{"ready":true}')).toEqual([])
    })

    it('keeps the known states, once each, in their order', () => {
        expect(parseStates('["done","ci_red","ready","done"]')).toEqual(['ready', 'done'])
    })
})

describe('withState', () => {
    it('turns a state on or off, keeping the order', () => {
        expect(withState(['done'], 'blocked', true)).toEqual(['blocked', 'done'])
        expect(withState(['blocked', 'done'], 'blocked', false)).toEqual(['done'])
        expect(withState([], 'ready', false)).toEqual([])
    })
})

describe('ticketToasts', () => {
    const all = TICKET_TOAST_STATES

    it("toasts a ticket's phase moving into a state turned on, with its key over its title", () => {
        const before = [ticket({ phase: 'running' })]
        const after = [ticket({ phase: 'needs_human' })]
        expect(ticketToasts(before, after, ['needs_human'])).toEqual([
            { title: 'ABC-102: needs human', detail: 'Export reports as CSV', tone: 'moved' },
        ])
    })

    it('toasts a ticket marked done, and a title-less one without a detail', () => {
        const before = [ticket({ title: null })]
        const after = [ticket({ title: null, done: true })]
        expect(ticketToasts(before, after, ['done'])).toEqual([{ title: 'ABC-102: done', tone: 'moved' }])
    })

    it('says nothing of a state turned off, a phase that stayed, or a ticket leaving a state', () => {
        expect(ticketToasts([ticket({ phase: 'running' })], [ticket({ phase: 'ready' })], ['blocked'])).toEqual([])
        expect(ticketToasts([ticket({ phase: 'ready' })], [ticket({ phase: 'ready' })], all)).toEqual([])
        expect(ticketToasts([ticket({ phase: 'ready', done: true })], [ticket({ phase: null })], all)).toEqual([])
    })

    it('toasts a ticket new to the list as moving from no phase, and nothing before the first list', () => {
        const after = [ticket({ key: 'ABC-200', phase: 'ready', title: null })]
        expect(ticketToasts([], after, ['ready'])).toEqual([{ title: 'ABC-200: ready', tone: 'moved' }])
        expect(ticketToasts(undefined, after, all)).toEqual([])
    })

    it("never toasts a PR's phase, which no checkbox turns on", () => {
        expect(ticketToasts([ticket({ phase: 'ready' })], [ticket({ phase: 'ci_red' })], all)).toEqual([])
    })
})

describe('useTicketToasts', () => {
    beforeEach(() => localStorage.clear())

    it('turns states on, and keeps them', async () => {
        const toasts = await load()
        const { result } = renderHook(() => toasts.useTicketToasts())
        expect(result.current).toEqual([])

        act(() => toasts.setTicketToasts(['blocked', 'done']))
        expect(result.current).toEqual(['blocked', 'done'])
        expect(localStorage.getItem(toasts.STORAGE_KEY)).toBe('["blocked","done"]')
    })

    it("follows another tab's states, ones stored before it was read, and storage cleared", async () => {
        const toasts = await load()
        localStorage.setItem(toasts.STORAGE_KEY, '["ready"]')
        const { result } = renderHook(() => toasts.useTicketToasts())
        expect(result.current).toEqual(['ready'])

        act(() => otherTab(toasts.STORAGE_KEY, '["split"]'))
        expect(result.current).toEqual(['split'])
        act(() => otherTabClears())
        expect(result.current).toEqual([])
    })

    it('turns none on where storage is unavailable, and still changes for this page', async () => {
        breakStorage()
        const toasts = await load()
        const { result } = renderHook(() => toasts.useTicketToasts())
        expect(result.current).toEqual([])

        act(() => toasts.setTicketToasts(['done']))
        expect(result.current).toEqual(['done'])
    })
})
