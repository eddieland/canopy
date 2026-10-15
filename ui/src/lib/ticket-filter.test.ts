import { describe, expect, it } from 'vitest'

import { mockTickets } from '@/api/mocks'
import type { TicketSummary } from '@/api/types'

import { TICKET_QUERY_MAX, ticketQueryOf, ticketShowOf, ticketShown } from './ticket-filter'

const base = mockTickets[0] as TicketSummary
const ticket = (fields: Partial<TicketSummary>): TicketSummary => ({ ...base, ...fields })

describe('ticketShowOf', () => {
    it('keeps a filter the page offers and drops anything else', () => {
        expect(ticketShowOf('waiting')).toBe('waiting')
        expect(ticketShowOf('done')).toBe('done')
        expect(ticketShowOf('blocked')).toBe('blocked')
        expect(ticketShowOf('stuck')).toBeUndefined()
        expect(ticketShowOf(['done'])).toBeUndefined()
        expect(ticketShowOf(undefined)).toBeUndefined()
    })
})

describe('ticketQueryOf', () => {
    it('keeps text with a word in it, cut to the longest it keeps', () => {
        expect(ticketQueryOf('csv')).toBe('csv')
        expect(ticketQueryOf('a b ')).toBe('a b ')
        expect(ticketQueryOf('x'.repeat(TICKET_QUERY_MAX + 5))).toHaveLength(TICKET_QUERY_MAX)
    })

    it('drops blank text and anything not a string', () => {
        expect(ticketQueryOf('')).toBeUndefined()
        expect(ticketQueryOf('   ')).toBeUndefined()
        expect(ticketQueryOf(102)).toBeUndefined()
        expect(ticketQueryOf(undefined)).toBeUndefined()
    })
})

describe('ticketShown', () => {
    const open = ticket({ done: false, awaiting: null, running_run: null })
    const working = ticket({ running_run: 41, awaiting: null })
    const waiting = ticket({ awaiting: 5, running_run: null })
    const blocked = ticket({ phase: 'blocked', awaiting: null, running_run: null })
    const done = ticket({ done: true, awaiting: null, running_run: null })

    it('shows every ticket with no filter', () => {
        for (const t of [open, working, waiting, blocked, done]) {
            expect(ticketShown(t, undefined, undefined)).toBe(true)
        }
    })

    it('keeps the tickets standing where the filter says', () => {
        const all = [open, working, waiting, blocked, done]
        expect(all.filter((t) => ticketShown(t, 'open', undefined))).toEqual([open, working, waiting, blocked])
        expect(all.filter((t) => ticketShown(t, 'working', undefined))).toEqual([working])
        expect(all.filter((t) => ticketShown(t, 'waiting', undefined))).toEqual([waiting])
        expect(all.filter((t) => ticketShown(t, 'blocked', undefined))).toEqual([blocked])
        expect(all.filter((t) => ticketShown(t, 'done', undefined))).toEqual([done])
    })

    it('keeps a ticket an open blocker holds, not one whose run asked a question', () => {
        expect(ticketShown(ticket({ phase: 'blocked' }), 'blocked', undefined)).toBe(true)
        expect(ticketShown(ticket({ phase: 'needs_human', awaiting: 5 }), 'blocked', undefined)).toBe(false)
    })

    it('finds every word of the text in the key or title, in any case', () => {
        expect(ticketShown(base, undefined, 'abc-10')).toBe(true)
        expect(ticketShown(base, undefined, 'CSV export')).toBe(true)
        expect(ticketShown(base, undefined, '  reports  ')).toBe(true)
        expect(ticketShown(base, undefined, 'csv pdf')).toBe(false)
        expect(ticketShown(base, undefined, 'agent')).toBe(false)
    })

    it('finds an untitled ticket by its key alone', () => {
        const untitled = ticket({ key: 'ABC-104', title: null })
        expect(ticketShown(untitled, undefined, '104')).toBe(true)
        expect(ticketShown(untitled, undefined, 'null')).toBe(false)
    })

    it('needs both filters to hold', () => {
        expect(ticketShown(waiting, 'waiting', 'csv')).toBe(true)
        expect(ticketShown(waiting, 'working', 'csv')).toBe(false)
        expect(ticketShown(waiting, 'waiting', 'sso')).toBe(false)
    })
})
