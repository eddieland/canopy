import { describe, expect, it } from 'vitest'

import { settled, withLeaving } from './leaving'
import type { Listed } from './leaving'

const a = { id: 'a' }
const b = { id: 'b' }
const c = { id: 'c' }
const d = { id: 'd' }

function shown(...items: { id: string }[]): Listed<{ id: string }>[] {
    return items.map((item) => ({ item, leaving: false }))
}

function ids(rows: Listed<{ id: string }>[]): string[] {
    return rows.map((row) => (row.leaving ? `${row.item.id}-` : row.item.id))
}

describe('withLeaving', () => {
    it('lists the items in their order when none has left', () => {
        expect(ids(withLeaving([], [a, b]))).toEqual(['a', 'b'])
        expect(ids(withLeaving(shown(a, b), [b, a, c]))).toEqual(['b', 'a', 'c'])
    })

    it('keeps a row whose item is gone where it was, leaving', () => {
        expect(ids(withLeaving(shown(a, b, c), [a, c]))).toEqual(['a', 'b-', 'c'])
        expect(ids(withLeaving(shown(a, b, c), [b, c]))).toEqual(['a-', 'b', 'c'])
        expect(ids(withLeaving(shown(a, b, c), [a, b]))).toEqual(['a', 'b', 'c-'])
        expect(ids(withLeaving(shown(a, b), []))).toEqual(['a-', 'b-'])
    })

    it('keeps rows already leaving, and adds the ones that leave next', () => {
        const once = withLeaving(shown(a, b, c, d), [a, c, d])
        expect(ids(withLeaving(once, [a, d]))).toEqual(['a', 'b-', 'c-', 'd'])
    })

    it('shows the latest copy of a staying item, and the last seen of a gone one', () => {
        const rows = withLeaving([{ item: { id: 'a', n: 1 }, leaving: false }], [{ id: 'a', n: 2 }])
        expect(rows).toEqual([{ item: { id: 'a', n: 2 }, leaving: false }])
        const gone = withLeaving([{ item: { id: 'a', n: 1 }, leaving: false }], [])
        expect(gone).toEqual([{ item: { id: 'a', n: 1 }, leaving: true }])
    })

    it('gives an item listed again its place back from its leaving row', () => {
        const once = withLeaving(shown(a, b), [a])
        expect(ids(withLeaving(once, [a, b]))).toEqual(['a', 'b'])
    })
})

describe('settled', () => {
    it('drops the rows that are leaving', () => {
        expect(ids(settled(withLeaving(shown(a, b, c), [b])))).toEqual(['b'])
    })
})
