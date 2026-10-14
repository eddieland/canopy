import { describe, expect, it } from 'vitest'

import { hit } from '@/api/mocks'

import { bySource, isSearchShortcut, marked, markedTokens, searchQueryOf } from './search'

describe('searchQueryOf', () => {
    it('collapses whitespace and keeps what the server accepts', () => {
        expect(searchQueryOf('  fix \t login ')).toBe('fix login')
        expect(searchQueryOf(123)).toBe('123')
    })

    it('drops what the server would refuse', () => {
        expect(searchQueryOf(undefined)).toBeUndefined()
        expect(searchQueryOf({ q: 'x' })).toBeUndefined()
        expect(searchQueryOf(' a ')).toBeUndefined()
        expect(searchQueryOf('x'.repeat(201))).toBeUndefined()
        expect(searchQueryOf('a b c d e f g h i')).toBeUndefined()
        // A repeated word counts once, as the server counts it.
        expect(searchQueryOf('a a a a a a a a a')).toBe('a a a a a a a a a')
    })
})

describe('marked', () => {
    it('marks each match of any word, letters in either case', () => {
        expect(marked('Search now debounces search', ['SEARCH'])).toEqual([
            { text: 'Search', mark: true },
            { text: ' now debounces ', mark: false },
            { text: 'search', mark: true },
        ])
    })

    it('prefers the longer word and takes regex characters literally', () => {
        expect(marked('a.b*c deb debounce', ['deb', 'debounce', 'a.b*'])).toEqual([
            { text: 'a.b*', mark: true },
            { text: 'c ', mark: false },
            { text: 'deb', mark: true },
            { text: ' ', mark: false },
            { text: 'debounce', mark: true },
        ])
        expect(marked('axb', ['a.b'])).toEqual([{ text: 'axb', mark: false }])
    })

    it('marks nothing without words', () => {
        expect(marked('text', [])).toEqual([{ text: 'text', mark: false }])
        expect(marked('', [])).toEqual([])
    })
})

describe('markedTokens', () => {
    it("cuts tokens where a match starts and ends, each piece keeping its token's fields", () => {
        const tokens = [
            { kind: 'key', text: '"title"' },
            { kind: 'punct', text: ':' },
            { kind: 'text', text: ' ' },
            { kind: 'string', text: '"Debounce"' },
        ]
        expect(markedTokens(tokens, ['title": "DEB'])).toEqual([
            { kind: 'key', text: '"', mark: false },
            { kind: 'key', text: 'title"', mark: true },
            { kind: 'punct', text: ':', mark: true },
            { kind: 'text', text: ' ', mark: true },
            { kind: 'string', text: '"Deb', mark: true },
            { kind: 'string', text: 'ounce"', mark: false },
        ])
    })

    it('marks nothing without words, and keeps every character', () => {
        const tokens = [{ text: 'a' }, { text: '' }, { text: 'bc' }]
        expect(markedTokens(tokens, [])).toEqual([
            { text: 'a', mark: false },
            { text: 'bc', mark: false },
        ])
        expect(markedTokens(tokens, ['b']).map((t) => t.text)).toEqual(['a', 'b', 'c'])
    })
})

describe('bySource', () => {
    it('groups hits in the server order, leaving out sources with none', () => {
        const hits = [hit({ source: 'tick' }), hit({ source: 'ticket' }), hit({ source: 'tick', tick_id: 2 })]
        expect(bySource(hits).map(([s, found]) => [s, found.length])).toEqual([
            ['ticket', 1],
            ['tick', 2],
        ])
    })
})

describe('isSearchShortcut', () => {
    const key = { key: '/', ctrlKey: false, metaKey: false, altKey: false }

    it('takes a bare slash outside a text field', () => {
        expect(isSearchShortcut(key, document.body)).toBe(true)
        expect(isSearchShortcut(key, null)).toBe(true)
    })

    it('leaves a slash typed into a field, or with a modifier, alone', () => {
        expect(isSearchShortcut(key, document.createElement('textarea'))).toBe(false)
        expect(isSearchShortcut(key, document.createElement('input'))).toBe(false)
        expect(isSearchShortcut({ ...key, ctrlKey: true }, document.body)).toBe(false)
        expect(isSearchShortcut({ ...key, key: '?' }, document.body)).toBe(false)
    })
})
