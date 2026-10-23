import { describe, expect, it } from 'vitest'

import { mockAttention, mockTasks, mockTickets } from '@/api/mocks'
import type { TaskSummary, TicketSummary } from '@/api/types'

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

    it('is not a plan review while its feedback plan waits, though its ticket plan does not', () => {
        const review = {
            ...item,
            reason: 'plan_review',
            detail: 'feedback plan 3 for https://github.com/acme/web/pull/88 waits: canopy plan ABC-102 --approve',
        }
        const plan = { id: 3, pr_urls: ['https://github.com/acme/web/pull/88'], items: 2, stale: true }
        expect(answered(review, listing({ plan_waits: false, feedback_plan: plan }))).toBe(false)
        // Approved, it waits on you no more, and the item leaves at the next tick.
        expect(answered(review, listing({ plan_waits: false, feedback_plan: null }))).toBe(true)
        // A later feedback plan waiting does not hold the item about this one.
        expect(answered(review, listing({ plan_waits: false, feedback_plan: { ...plan, id: 4 } }))).toBe(true)
    })

    it('is a ticket plan review answered by its own plan, whatever its feedback plan does', () => {
        const review = { ...item, reason: 'plan_review', detail: 'plan 7 waits: canopy show ABC-102, then ...' }
        const plan = { id: 3, pr_urls: ['https://github.com/acme/web/pull/88'], items: 2, stale: false }
        expect(answered(review, listing({ plan_waits: false, feedback_plan: plan }))).toBe(true)
        expect(answered(review, listing({ plan_waits: true, feedback_plan: null }))).toBe(false)
    })

    it('is a plan review naming no plan answered once neither plan waits', () => {
        const review = { ...item, reason: 'plan_review', detail: 'a plan waits' }
        const plan = { id: 3, pr_urls: ['https://github.com/acme/web/pull/88'], items: 2, stale: false }
        expect(answered(review, listing({ plan_waits: false, feedback_plan: plan }))).toBe(false)
        expect(answered(review, listing({ plan_waits: false, feedback_plan: null }))).toBe(true)
    })

    it('is never another reason', () => {
        expect(answered({ ...item, reason: 'worker_failed' }, listing({ awaiting: null }))).toBe(false)
    })

    describe("a task's question", () => {
        const asks = { ...item, id: 't4', subject: 'task:4', ticket_key: null, ticket_title: null, task: 4 }
        const waiting = mockTasks[2] as TaskSummary
        const tasks = (changes: Partial<TaskSummary>) => [{ ...waiting, ...changes }]

        it('is answered once the task waits on no reply: replied to, or stopped', () => {
            expect(answered(asks, mockTickets, tasks({ standing: 'queued', question_id: null }))).toBe(true)
            expect(answered(asks, mockTickets, tasks({ standing: 'stopped', question_id: null }))).toBe(true)
        })

        it('is not while the task still waits on you, or the tasks are not loaded', () => {
            expect(answered(asks, mockTickets, tasks({}))).toBe(false)
            expect(answered(asks, mockTickets, undefined)).toBe(false)
            expect(answered(asks, mockTickets)).toBe(false)
        })

        it("is never a task's other reason, which the next tick clears", () => {
            const unrecorded = { ...asks, reason: 'task_ticket_unrecorded' }
            expect(answered(unrecorded, mockTickets, tasks({ standing: 'stopped' }))).toBe(false)
        })
    })
})
