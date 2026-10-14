import { describe, expect, it } from 'vitest'

import { choreRef, choreRunRef, reviewRef, runRef, tickRef } from './refs'

describe('refs', () => {
    it('names each kind as KIND:ID, the grammar the CLI reads', () => {
        expect(runRef(41)).toBe('run:41')
        expect(reviewRef(4)).toBe('review:4')
        expect(tickRef(2)).toBe('tick:2')
        expect(choreRef('deps')).toBe('chore:deps')
    })

    it("names a chore run by its chore's reference and its number", () => {
        expect(choreRunRef('deps', 2)).toBe('chore:deps#2')
        expect(choreRunRef('deps', '2')).toBe('chore:deps#2')
    })
})
