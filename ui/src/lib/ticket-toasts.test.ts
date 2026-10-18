import { describe, expect, it } from 'vitest'

import { mockTickets } from '@/api/mocks'
import type { TicketSummary } from '@/api/types'
import { TOAST_STATES } from '@/lib/toast-settings'

import { ticketToasts } from './ticket-toasts'

function ticket(fields: Partial<TicketSummary>): TicketSummary {
    const [base] = mockTickets
    if (!base) {
        throw new Error('no mock ticket')
    }
    return { ...base, ...fields }
}

describe('ticketToasts', () => {
    const all = TOAST_STATES.tickets

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
