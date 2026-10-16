import { describe, expect, it } from 'vitest'

import { ATOM } from '@/lib/plan-anchors'

import {
    addReply,
    addThread,
    changeRequest,
    inPlanOrder,
    removeThread,
    setResolved,
    withAnchors,
} from '@/lib/plan-threads'
import type { PlanThread } from '@/lib/plan-threads'

const AT = '2026-10-08T12:00:00Z'
const anchor = (quote: string) => ({ quote, prefix: '', suffix: '' })

function two(): PlanThread[] {
    let threads = addThread([], { id: 'a', anchor: anchor('streams rows'), body: 'Page instead?', at: AT })
    threads = addThread(threads, { id: 'b', anchor: anchor('Add a CSV export'), body: 'Name the route.', at: AT })
    return threads
}

describe('threads', () => {
    it('adds, replies, resolves, and removes without changing the list it was given', () => {
        const threads = two()
        const replied = addReply(threads, 'a', { id: 'r1', body: 'Or both.', at: AT })
        expect(threads[0]?.replies).toEqual([])
        expect(replied[0]?.replies.map((r) => r.body)).toEqual(['Or both.'])
        expect(setResolved(replied, 'a', true)[0]?.resolved).toBe(true)
        expect(removeThread(replied, 'a').map((t) => t.id)).toEqual(['b'])
    })

    it('keeps the same list when no anchor moved', () => {
        const threads = two()
        expect(withAnchors(threads, new Map([['a', anchor('streams rows')]]))).toBe(threads)
        const moved = withAnchors(threads, new Map([['a', { quote: 'streams rows', prefix: 'x', suffix: '' }]]))
        expect(moved).not.toBe(threads)
        expect(moved[0]?.anchor.prefix).toBe('x')
    })

    it('orders threads as the plan reads, with the lost ones last', () => {
        const starts = new Map([
            ['b', 1],
            ['a', 30],
        ])
        expect(inPlanOrder(two(), starts).map((t) => t.id)).toEqual(['b', 'a'])
        expect(inPlanOrder(two(), new Map([['a', 5]])).map((t) => t.id)).toEqual(['a', 'b'])
    })
})

describe('changeRequest', () => {
    it('asks for each open comment on its passage, in plan order, then the note', () => {
        let threads = addReply(two(), 'a', { id: 'r1', body: 'Or both.', at: AT })
        threads = addThread(threads, { id: 'c', anchor: anchor('large report'), body: 'Done.', at: AT })
        threads = setResolved(threads, 'c', true)
        const starts = new Map([
            ['b', 0],
            ['a', 20],
            ['c', 40],
        ])
        expect(changeRequest(threads, starts, 'Keep it small.')).toBe(
            [
                'Change the plan where I commented. Each comment quotes the passage it is on.',
                '',
                '1. On "Add a CSV export":',
                '   Name the route.',
                '',
                '2. On "streams rows":',
                '   Page instead?',
                '   Reply: Or both.',
                '',
                'On the whole plan:',
                'Keep it small.',
            ].join('\n'),
        )
    })

    it('says which passages are gone, and is empty with nothing to ask', () => {
        expect(changeRequest(two(), new Map([['b', 0]]))).toContain('2. On "streams rows" (no longer in the plan):')
        expect(changeRequest(setResolved(two().slice(0, 1), 'a', true), new Map())).toBe('')
        expect(changeRequest([], new Map(), '  Shorter.  ')).toBe('Shorter.')
    })

    it('quotes a passage without the placeholders its tags stand as in the editor', () => {
        const threads = addThread([], { id: 'a', anchor: anchor(`Use ${ATOM}raw${ATOM} rows`), body: 'Why?', at: AT })
        expect(changeRequest(threads, new Map([['a', 0]]))).toContain('1. On "Use raw rows":')
    })

    it('cuts a long passage in the request, not in the thread', () => {
        const long = 'word '.repeat(100).trim()
        const threads = addThread([], { id: 'a', anchor: anchor(long), body: 'Too much.', at: AT })
        const request = changeRequest(threads, new Map([['a', 0]]))
        expect(request).toContain('…"')
        expect(request.length).toBeLessThan(long.length)
    })
})
