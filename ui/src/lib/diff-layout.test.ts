import { describe, expect, it } from 'vitest'

import type { DiffLine } from '@/api/types'

import { parseLayout, splitRows } from './diff-layout'

/** Lines of the kinds written, one letter each: `c` unchanged, `d` removed, `a` added. */
function lines(kinds: string): DiffLine[] {
    return kinds.split('').map((kind, i) => ({
        kind: kind === 'a' ? 'add' : kind === 'd' ? 'del' : 'ctx',
        old: null,
        new: null,
        text: `line ${i}`,
    }))
}

describe('parseLayout', () => {
    it('reads split, and unified from anything else', () => {
        expect(parseLayout('split')).toBe('split')
        expect(parseLayout('unified')).toBe('unified')
        expect(parseLayout(null)).toBe('unified')
        expect(parseLayout('sideways')).toBe('unified')
    })
})

describe('splitRows', () => {
    it('puts an unchanged line on both sides, and removed lines beside the added ones that follow', () => {
        expect(splitRows(lines('cddac'), [], 0, 5)).toEqual([
            { old: 0, new: 0 },
            { old: 1, new: 3 },
            { old: 2, new: undefined },
            { old: 4, new: 4 },
        ])
    })

    it('puts a removed line beside the added line it is paired with, the lines added before it alone', () => {
        // The one removed line is paired with the third added line.
        expect(splitRows(lines('daaa'), [3], 0, 4)).toEqual([
            { old: undefined, new: 1 },
            { old: undefined, new: 2 },
            { old: 0, new: 3 },
        ])
    })

    it('leaves lines only added, or only removed, alone on their side', () => {
        expect(splitRows(lines('aacd'), [], 0, 4)).toEqual([
            { old: undefined, new: 0 },
            { old: undefined, new: 1 },
            { old: 2, new: 2 },
            { old: 3, new: undefined },
        ])
    })

    it('lays out only the lines in its range, and ignores a pair that leaves it', () => {
        expect(splitRows(lines('ddaa'), [2, 3], 1, 3)).toEqual([{ old: 1, new: 2 }])
        expect(splitRows(lines('ddaa'), [3], 0, 3)).toEqual([
            { old: 0, new: 2 },
            { old: 1, new: undefined },
        ])
    })
})
