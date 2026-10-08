import { describe, expect, it } from 'vitest'

import { rollCells } from './roll'

describe('rollCells', () => {
    it('splits digits from other glyphs, in reading order', () => {
        expect(rollCells('$4.20')).toEqual([
            { key: '4g', kind: 'glyph', glyph: '$' },
            { key: '3d', kind: 'digit', digit: 4, place: 2 },
            { key: '2g', kind: 'glyph', glyph: '.' },
            { key: '1d', kind: 'digit', digit: 2, place: 1 },
            { key: '0d', kind: 'digit', digit: 0, place: 0 },
        ])
    })

    it('keys by place from the right, so a new leading digit leaves the others in place', () => {
        const before = rollCells('9').map((c) => c.key)
        const after = rollCells('10').map((c) => c.key)
        expect(after.slice(-before.length)).toEqual(before)
        expect(
            rollCells('$14.20')
                .slice(-5)
                .map((c) => c.key),
        ).toEqual(
            rollCells('$4.20')
                .map((c) => c.key)
                .with(0, '4d'),
        )
    })

    it('keeps a placeholder as a glyph', () => {
        expect(rollCells('–')).toEqual([{ key: '0g', kind: 'glyph', glyph: '–' }])
    })
})
