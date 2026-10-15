import { describe, expect, it } from 'vitest'

import { LISTS, orderWords, ordered, parseOrders, withOrder } from './list-order'

describe('parseOrders', () => {
    it('chooses nothing when nothing is stored', () => {
        expect(parseOrders(null)).toEqual({})
    })

    it('reads the orders stored', () => {
        expect(parseOrders('{"conversation":"newest","ticks":"oldest"}')).toEqual({
            conversation: 'newest',
            ticks: 'oldest',
        })
    })

    it('keeps only lists and orders it knows, and reads anything else as none', () => {
        expect(parseOrders('{"conversation":"sideways","worktrees":"newest","runs":"oldest"}')).toEqual({
            runs: 'oldest',
        })
        expect(parseOrders('{"toString":"newest"}')).toEqual({})
        expect(parseOrders('not json')).toEqual({})
        expect(parseOrders('["conversation"]')).toEqual({})
        expect(parseOrders('null')).toEqual({})
    })
})

describe('withOrder', () => {
    it('sets one list and leaves the others as they were', () => {
        expect(withOrder({ ticks: 'oldest' }, 'conversation', 'newest')).toBe(
            '{"conversation":"newest","ticks":"oldest"}',
        )
    })

    it('leaves out a list put back in its own order, so a change to that order reaches it', () => {
        expect(LISTS.conversation).toBe('oldest')
        expect(withOrder({ conversation: 'newest', ticks: 'oldest' }, 'conversation', 'oldest')).toBe(
            '{"ticks":"oldest"}',
        )
        expect(withOrder({}, 'runs', 'newest')).toBe('{}')
    })
})

describe('ordered', () => {
    it('keeps a list in its own order, and reverses it in the other, leaving what it was given as it was', () => {
        const messages = [1, 2, 3]
        expect(ordered('conversation', 'oldest', messages)).toEqual([1, 2, 3])
        expect(ordered('conversation', 'newest', messages)).toEqual([3, 2, 1])
        expect(ordered('runs', 'newest', messages)).toEqual([1, 2, 3])
        expect(ordered('runs', 'oldest', messages)).toEqual([3, 2, 1])
        expect(messages).toEqual([1, 2, 3])
    })
})

describe('orderWords', () => {
    it('names a list in time by its newest or oldest end', () => {
        expect(orderWords('ticks', 'newest')).toBe('newest first')
        expect(orderWords('conversation', 'oldest')).toBe('oldest first')
    })

    it('names a list by activity by when its rows were last updated, not when they began', () => {
        expect(orderWords('tickets', 'newest')).toBe('recently updated')
        expect(orderWords('pull-requests', 'oldest')).toBe('least recently updated')
        expect(orderWords('runs', 'newest')).toBe('recently updated')
    })
})
