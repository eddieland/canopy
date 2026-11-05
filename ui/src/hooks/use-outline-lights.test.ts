import { describe, expect, it } from 'vitest'

import { litOf, point } from './use-outline-lights'

describe('point', () => {
    it('keeps what the focus points at while the mouse comes and goes, and the other way round', () => {
        let pointed = point({ hover: null, focus: null }, { by: 'focus', id: 'C1', on: true })
        pointed = point(pointed, { by: 'hover', id: 'R1', on: true })
        expect(litOf(pointed)).toBe('R1')
        pointed = point(pointed, { by: 'hover', id: 'R1', on: false })
        expect(litOf(pointed)).toBe('C1')
        pointed = point(pointed, { by: 'hover', id: 'B2', on: true })
        pointed = point(pointed, { by: 'focus', id: 'C1', on: false })
        expect(litOf(pointed)).toBe('B2')
    })

    it('leaves an id put out only while it still points at it', () => {
        const pointed = point({ hover: 'R2', focus: null }, { by: 'hover', id: 'R1', on: false })
        expect(pointed).toEqual({ hover: 'R2', focus: null })
        expect(litOf({ hover: null, focus: null })).toBeNull()
    })
})
