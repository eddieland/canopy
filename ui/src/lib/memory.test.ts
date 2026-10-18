import { describe, expect, it } from 'vitest'

import {
    dueForReview,
    lapsesText,
    leftOutText,
    lessonChars,
    memorySegments,
    readNothingText,
    repoChoices,
    ticketNotesUsedText,
    usedText,
    visibleText,
} from './memory'

describe('visibleText', () => {
    it('names every character that hides text by its code point, as canopy memory list does', () => {
        expect(visibleText('safe \u202Eevil\u202C and\u200Bthis\u001B[2J')).toBe(
            'safe <U+202E>evil<U+202C> and<U+200B>this<U+001B>[2J',
        )
        // A tag character, outside the basic plane, by its whole code point.
        expect(visibleText('a\u{E0041}b')).toBe('a<U+E0041>b')
        expect(visibleText('line\nbreak\u2028sep')).toBe('line<U+000A>break<U+2028>sep')
    })

    it('leaves Markdown and links as the characters they are', () => {
        const text = 'See [the fix](https://evil.test) and **this**.'
        expect(visibleText(text)).toBe(text)
        expect(memorySegments(text)).toEqual([{ text, hidden: false }])
    })

    it('cuts the text where each hidden character is', () => {
        expect(memorySegments('a\u200Bb')).toEqual([
            { text: 'a', hidden: false },
            { text: '<U+200B>', hidden: true },
            { text: 'b', hidden: false },
        ])
        expect(memorySegments('')).toEqual([])
    })
})

describe('usedText', () => {
    it('says a memory no run used was read by none, and one used how often', () => {
        expect(usedText({ use_count: 0, last_used_at: null })).toBe('read by no run')
        expect(usedText({ use_count: 1, last_used_at: '2026-10-08T11:00:00Z' })).toBe('used by 1 run')
        expect(usedText({ use_count: 3, last_used_at: '2026-10-08T11:00:00Z' })).toBe('used by 3 runs')
    })
})

describe('readNothingText', () => {
    it('tells a run that read nothing because it was recording from one whose digest was empty', () => {
        expect(readNothingText(false)).toBe('none, recording only')
        expect(readNothingText(true)).toBe('none')
    })
})

describe('ticketNotesUsedText', () => {
    it('says how many of a ticket’s notes in force a run relied on, or that none was read', () => {
        expect(ticketNotesUsedText({ count: 4, used: 0 })).toBe('read by no run')
        expect(ticketNotesUsedText({ count: 4, used: 3 })).toBe('3 of 4 used by runs')
    })
})

describe('leftOutText', () => {
    it('never says a recording tier’s left-out memory is left out of a prompt that is served', () => {
        expect(leftOutText(true)).toBe('left out of the prompt, past its cap')
        expect(leftOutText(false)).toBe('would be left out at use, past its cap')
    })
})

describe('lessonChars', () => {
    it('counts code points past the spaces at either end, as the server bounds a lesson', () => {
        expect(lessonChars('  two words  ')).toBe(9)
        expect(lessonChars('a\u{1F600}b')).toBe(3)
        expect(lessonChars('   ')).toBe(0)
    })
})

describe('repoChoices', () => {
    it('offers every repository only for a source that names none, and a proposal its own first', () => {
        expect(repoChoices({ repo: null }, ['api', 'web'])).toEqual([null, 'api', 'web'])
        expect(repoChoices({ repo: 'web' }, ['api', 'web'])).toEqual(['web', 'api'])
        // Kept though the workspace map dropped it: promoting as written leaves the proposal's repository as it is.
        expect(repoChoices({ repo: 'gone' }, ['api'])).toEqual(['gone', 'api'])
    })
})

describe('dueForReview', () => {
    it('keeps the lessons whose review date has come, the longest overdue first', () => {
        const now = Date.parse('2026-10-08T12:00:00Z')
        const lessons = [
            { id: 1, review_at: '2026-10-08T11:00:00Z' },
            { id: 2, review_at: '2026-10-09T00:00:00Z' },
            { id: 3, review_at: '2026-09-01T00:00:00Z' },
            { id: 4, review_at: null },
            { id: 5, review_at: '2026-10-08T12:00:00Z' },
        ]
        expect(dueForReview(lessons, now).map((m) => m.id)).toEqual([3, 1, 5])
    })
})

describe('lapsesText', () => {
    const now = Date.parse('2026-10-08T12:00:00Z')

    it('says how long a proposal has left, in the largest whole unit', () => {
        expect(lapsesText('2026-10-11T13:00:00Z', now)).toBe('lapses in 3d')
        expect(lapsesText('2026-10-08T15:30:00Z', now)).toBe('lapses in 3h')
    })

    it('says a proposal past its time lapses at the next tick, which invalidates it', () => {
        expect(lapsesText('2026-10-08T12:00:00Z', now)).toBe('lapses at the next tick')
        expect(lapsesText('2026-10-01T12:00:00Z', now)).toBe('lapses at the next tick')
    })
})
