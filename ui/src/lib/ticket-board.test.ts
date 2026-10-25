import { describe, expect, it } from 'vitest'

import { mockTickets } from '@/api/mocks'
import type { TicketSummary } from '@/api/types'

import { BOARD_COLUMNS, boardColumn, boardOf, mostRecent } from './ticket-board'

const base = mockTickets[0] as TicketSummary
const ticket = (fields: Partial<TicketSummary>): TicketSummary => ({ ...base, ...fields })
// The column of a ticket in `phase` with no run on it.
const at = (phase: string | null) => boardColumn(ticket({ phase, running_run: null, done: false }))

describe('boardColumn', () => {
    it('puts each phase in the stage it is at', () => {
        expect(at('ready')).toBe('todo')
        expect(at('blocked')).toBe('todo')
        expect(at('needs_human')).toBe('todo')
        expect(at('plan_proposed')).toBe('plan')
        expect(at('running')).toBe('working')
        expect(at('pushed_no_pr')).toBe('working')
        expect(at('conflicted')).toBe('ci')
        expect(at('ci_red')).toBe('ci')
        expect(at('review_pending')).toBe('review')
        expect(at('changes_requested')).toBe('review')
        expect(at('green_unreviewed')).toBe('review')
        expect(at('approved')).toBe('approved')
        expect(at('merged')).toBe('done')
    })

    it('puts a ticket no tick has phased, or in a phase it does not know, in to do', () => {
        expect(at(null)).toBe('todo')
        expect(at('somewhere_new')).toBe('todo')
    })

    it('puts a ticket a run is on in working, whatever its phase, and a done one in done', () => {
        expect(boardColumn(ticket({ phase: 'ci_red', running_run: 43, done: false }))).toBe('working')
        expect(boardColumn(ticket({ phase: 'blocked', running_run: null, done: true }))).toBe('done')
        expect(boardColumn(ticket({ phase: 'running', running_run: 43, done: true }))).toBe('done')
    })
})

describe('boardOf', () => {
    it('gives every column, each with its tickets in the order given', () => {
        const board = boardOf([
            ticket({ key: 'A-1', phase: 'ci_red', running_run: null }),
            ticket({ key: 'A-2', phase: 'review_pending', running_run: null }),
            ticket({ key: 'A-3', phase: 'ci_running', running_run: null }),
        ])
        expect(Object.keys(board)).toEqual([...BOARD_COLUMNS])
        expect(board.ci.map((t) => t.key)).toEqual(['A-1', 'A-3'])
        expect(board.review.map((t) => t.key)).toEqual(['A-2'])
        expect(board.todo).toEqual([])
    })
})

describe('mostRecent', () => {
    it('keeps the most recently active, in the order given, whichever end that is', () => {
        const days = [1, 2, 3, 4, 5].map((day) => ticket({ key: `D-${day}`, active_at: `2026-10-0${day}T12:00:00Z` }))
        expect(mostRecent(days.toReversed(), 2).map((t) => t.key)).toEqual(['D-5', 'D-4'])
        expect(mostRecent(days, 2).map((t) => t.key)).toEqual(['D-4', 'D-5'])
        expect(mostRecent(days, 9)).toHaveLength(5)
    })
})
