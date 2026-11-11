import { describe, expect, it } from 'vitest'

import { kindWord } from './diagram-picture'

describe('kindWord', () => {
    it.each([
        ['flowchart-v2', 'flowchart'],
        ['sequence', 'sequence'],
        ['stateDiagram', 'state'],
        ['classDiagram', 'class'],
        ['class', 'class'],
        ['er', 'er'],
        ['pie', 'diagram'],
    ])('names a %s diagram in a file as %s', (kind, word) => {
        expect(kindWord(kind)).toBe(word)
    })
})
