import { describe, expect, it } from 'vitest'

import type { DiffFile } from '@/api/types'

import { filesSummary, MAX_VIEWED, parseViewed, viewedMark, viewedOf, withViewed } from './viewed-files'

/** A file at `path` whose diff adds each of `lines`. */
function file(path: string, ...lines: string[]): DiffFile {
    return {
        path,
        old_path: null,
        binary: false,
        hunks: [{ header: '', lines: lines.map((text, i) => ({ kind: 'add', old: null, new: i + 1, text })) }],
    }
}

describe('viewedMark', () => {
    it('is the same for the same change, and another for another path or another line', () => {
        expect(viewedMark(file('a.ts', 'one'))).toBe(viewedMark(file('a.ts', 'one')))
        expect(viewedMark(file('a.ts', 'one'))).not.toBe(viewedMark(file('b.ts', 'one')))
        expect(viewedMark(file('a.ts', 'one'))).not.toBe(viewedMark(file('a.ts', 'two')))
        expect(viewedMark(file('a.ts', 'one'))).not.toBe(viewedMark({ ...file('a.ts', 'one'), old_path: 'b.ts' }))
    })
})

describe('viewedOf', () => {
    it('finds a file viewed only while its change is the one marked', () => {
        const marks = new Set([viewedMark(file('a.ts', 'one'))])
        expect(viewedOf([file('a.ts', 'one'), file('a.ts', 'one', 'two'), file('b.ts', 'one')], marks)).toEqual([
            true,
            false,
            false,
        ])
    })
})

describe('parseViewed', () => {
    it('reads the marks stored, and none from anything else', () => {
        expect(parseViewed('["a.ts@1f", 2, null]')).toEqual(['a.ts@1f'])
        expect(parseViewed(null)).toEqual([])
        expect(parseViewed('{"a":1}')).toEqual([])
        expect(parseViewed('not json')).toEqual([])
    })
})

describe('withViewed', () => {
    it('adds a mark as the newest, once, and removes one', () => {
        expect(withViewed(['a', 'b'], 'a', true)).toEqual(['b', 'a'])
        expect(withViewed(['a', 'b'], 'a', false)).toEqual(['b'])
    })

    it('drops the oldest past its bound', () => {
        const full = Array.from({ length: MAX_VIEWED }, (_, i) => `f${i}`)
        const next = withViewed(full, 'new', true)
        expect(next).toHaveLength(MAX_VIEWED)
        expect(next[0]).toBe('f1')
        expect(next.at(-1)).toBe('new')
    })
})

describe('filesSummary', () => {
    it('counts the files, and those viewed once any is', () => {
        expect(filesSummary([false])).toBe('1 file')
        expect(filesSummary([false, false])).toBe('2 files')
        expect(filesSummary([true, false, true])).toBe('3 files, 2 viewed')
    })
})
