import { describe, expect, it } from 'vitest'

import { ATOM } from '@/lib/plan-anchors'
import {
    addReply,
    addThread,
    approvalNotes,
    changeRequest,
    EDITED,
    editReply,
    editThread,
    fromServer,
    inPlanOrder,
    movedAnchors,
    removeThread,
    setResolved,
    threadChanges,
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

    it('edits a comment or one reply, and only that, without changing the list it was given', () => {
        const threads = addReply(two(), 'a', { id: 'r1', body: 'Or both.', at: AT })
        const edited = editThread(threads, 'a', 'Page it instead?')
        expect(threads[0]?.body).toBe('Page instead?')
        expect(edited.map((t) => t.body)).toEqual(['Page it instead?', 'Name the route.'])
        const reply = editReply(edited, 'a', 'r1', 'Or do both.')
        expect(reply[0]?.replies.map((r) => r.body)).toEqual(['Or do both.'])
        expect(edited[0]?.replies.map((r) => r.body)).toEqual(['Or both.'])
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

    it('says the plan was edited, after what it asks, and never asks for that alone', () => {
        expect(changeRequest([], new Map(), 'Shorter.', true)).toBe(`Shorter.\n\n${EDITED}`)
        expect(changeRequest([], new Map(), '', true)).toBe('')
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

    it("asks with the answers to the plan's decisions, after the comments and before the note, or alone", () => {
        const answers = ['Decision 1 (Where the hour is kept): take B, not A.', 'Decision 2 (Retries): take C, not A.']
        const request = changeRequest(two(), new Map([['a', 0]]), 'Shorter.', true, answers)
        expect(request).toContain(
            `   Name the route.\n\n${answers.join('\n')}\n\nOn the whole plan:\nShorter.\n\n${EDITED}`,
        )
        expect(changeRequest([], new Map(), '', false, answers)).toBe(answers.join('\n'))
        expect(changeRequest([], new Map(), 'Shorter.', false, answers.slice(0, 1))).toBe(
            `${answers[0] ?? ''}\n\nOn the whole plan:\nShorter.`,
        )
    })

    it('cuts a long passage in the request, not in the thread', () => {
        const long = 'word '.repeat(100).trim()
        const threads = addThread([], { id: 'a', anchor: anchor(long), body: 'Too much.', at: AT })
        const request = changeRequest(threads, new Map([['a', 0]]))
        expect(request).toContain('…"')
        expect(request.length).toBeLessThan(long.length)
    })
})

describe('approvalNotes', () => {
    it('carries each open comment on its passage, in plan order, then the note, and nothing of edits', () => {
        const starts = new Map([
            ['b', 0],
            ['a', 20],
        ])
        expect(approvalNotes(setResolved(two(), 'a', true), starts, 'Keep it small.')).toBe(
            [
                'Where I commented on the plan, do as I say. Each comment quotes the passage it is on.',
                '',
                '1. On "Add a CSV export":',
                '   Name the route.',
                '',
                'On the whole plan:',
                'Keep it small.',
            ].join('\n'),
        )
        expect(approvalNotes([], new Map(), ' Shorter. ')).toBe('Shorter.')
        expect(approvalNotes(setResolved(two(), 'a', true), new Map(), '').startsWith('Where I commented')).toBe(true)
        expect(approvalNotes([], new Map(), '  ')).toBe('')
    })

    it("carries the answers to the plan's decisions, even with no comment or note", () => {
        const answer = 'Decision 1 (Where the hour is kept): take B, not A.'
        expect(approvalNotes([], new Map(), '', [answer])).toBe(answer)
        expect(approvalNotes([], new Map(), 'Shorter.', [answer])).toBe(`${answer}\n\nOn the whole plan:\nShorter.`)
    })
})

describe('the journal', () => {
    it("reads the journal's threads with its ids as text", () => {
        const [thread] = fromServer([
            {
                id: 7,
                quote: 'streams rows',
                prefix: 'It ',
                suffix: '.',
                body: 'Page instead?',
                at: AT,
                resolved: true,
                replies: [{ id: 9, body: 'Or both.', at: AT }],
            },
        ])
        expect(thread).toEqual({
            id: '7',
            anchor: { quote: 'streams rows', prefix: 'It ', suffix: '.' },
            body: 'Page instead?',
            at: AT,
            resolved: true,
            replies: [{ id: '9', body: 'Or both.', at: AT }],
        })
    })

    it('names the writes from one list to the next, new threads first and deletions last', () => {
        const before = two()
        let after = removeThread(before, 'b')
        after = editThread(after, 'a', 'Page it.')
        after = setResolved(after, 'a', true)
        after = addReply(after, 'a', { id: 'r1', body: 'Or both.', at: AT })
        after = addThread(after, { id: 'c', anchor: anchor('the route'), body: 'Which?', at: AT })
        expect(threadChanges(before, after)).toEqual([
            { kind: 'edit', id: 'a', body: 'Page it.' },
            { kind: 'resolve', id: 'a', resolved: true },
            { kind: 'reply', id: 'a', body: 'Or both.' },
            { kind: 'add', thread: after[1] },
            { kind: 'delete', id: 'b' },
        ])
        expect(threadChanges(after, editReply(after, 'a', 'r1', 'Both.'))).toEqual([
            { kind: 'edit-reply', id: 'a', replyId: 'r1', body: 'Both.' },
        ])
    })

    it('leaves a moved passage to the save, and names it there', () => {
        const before = two()
        const moved = withAnchors(before, new Map([['a', anchor('streams the rows')]]))
        expect(threadChanges(before, moved)).toEqual([])
        expect(movedAnchors(before, moved).map((thread) => thread.id)).toEqual(['a'])
        expect(movedAnchors(before, before)).toEqual([])
    })
})
