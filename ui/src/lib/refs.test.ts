import { describe, expect, it } from 'vitest'

import { choreRef, choreRunRef, memoryRef, messageRef, reviewRef, runRef, slotRef, tickRef } from './refs'

describe('refs', () => {
    it('names each kind as KIND:ID, the grammar the CLI reads', () => {
        expect(runRef(41)).toBe('run:41')
        expect(reviewRef(4)).toBe('review:4')
        expect(tickRef(2)).toBe('tick:2')
        expect(memoryRef(3)).toBe('memory:3')
        expect(choreRef('deps')).toBe('chore:deps')
    })

    it("names a chore run by its chore's reference and its number", () => {
        expect(choreRunRef('deps', 2)).toBe('chore:deps#2')
        expect(choreRunRef('deps', '2')).toBe('chore:deps#2')
    })

    it('numbers a message and a slot as their lists do', () => {
        expect(messageRef(5)).toBe('#5')
        expect(slotRef('3')).toBe('#3')
    })
})
