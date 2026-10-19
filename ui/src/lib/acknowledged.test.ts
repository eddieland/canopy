import { describe, expect, it } from 'vitest'

import { mockAttention, mockTickets } from '@/api/mocks'
import type { TicketSummary } from '@/api/types'

import { answered, awaitsTick } from './acknowledged'

describe('awaitsTick', () => {
    it('holds an operator message newer than what the latest ok tick read', () => {
        expect(awaitsTick({ id: 8, source: 'operator' }, 7)).toBe(true)
        expect(awaitsTick({ id: 7, source: 'operator' }, 7)).toBe(false)
        expect(awaitsTick({ id: 3, source: 'operator' }, null)).toBe(true)
    })

    it('never holds a worker or tracker message', () => {
        expect(awaitsTick({ id: 8, source: 'worker' }, 7)).toBe(false)
        expect(awaitsTick({ id: 8, source: 'tracker' }, null)).toBe(false)
    })
})

describe('answered', () => {
    const [item] = mockAttention
    const [ticket] = mockTickets
    if (!item || !ticket) {
        throw new Error('fixtures are empty')
    }
    const listing = (changes: Partial<TicketSummary>) => [{ ...ticket, ...changes }]

    it('is an awaiting_reply item whose started ticket waits on nothing now', () => {
        expect(answered(item, listing({ awaiting: null }))).toBe(true)
    })

    it("is a public ticket's planner question answered", () => {
        expect(answered(item, listing({ awaiting: null, start: null, private: false }))).toBe(true)
    })

    it('is not while the question still waits, the ticket is stopped, or the tickets are not loaded', () => {
        expect(answered(item, listing({}))).toBe(false)
        expect(answered(item, listing({ awaiting: null, start: 'stopped' }))).toBe(false)
        expect(answered(item, undefined)).toBe(false)
    })

    it('is a plan review whose plan waits on you no more: approved, skipped, or sent back for changes', () => {
        const review = { ...item, reason: 'plan_review' }
        expect(answered(review, listing({ plan_waits: false }))).toBe(true)
        expect(answered(review, listing({ plan_waits: true }))).toBe(false)
        expect(answered(review, undefined)).toBe(false)
    })

    it('is never another reason', () => {
        expect(answered({ ...item, reason: 'worker_failed' }, listing({ awaiting: null }))).toBe(false)
    })
})
