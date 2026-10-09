import { describe, expect, it } from 'vitest'

import { HEADLINES, headlinesFor, parseHeadline } from './headlines'

describe('headlinesFor', () => {
    const day = 86_400_000
    const now = Date.parse('2026-10-08T12:30:00Z')

    it('lists every headline once', () => {
        expect([...headlinesFor(now)].toSorted()).toEqual([...HEADLINES].toSorted())
    })

    it('keeps one lead all day and moves to the next one the day after', () => {
        const lead = headlinesFor(now)[0]
        const start = Math.floor(now / day) * day
        expect(headlinesFor(start)[0]).toBe(lead)
        expect(headlinesFor(start + day - 1)[0]).toBe(lead)
        expect(headlinesFor(start + day)[0]).toBe(headlinesFor(now)[1])
    })

    it('has no two headlines alike, since each is its own key', () => {
        expect(new Set(HEADLINES).size).toBe(HEADLINES.length)
    })
})

describe('parseHeadline', () => {
    it('reads a color, then an effect, off the front', () => {
        expect(parseHeadline('flash2:wave:Hello')).toEqual({ text: 'Hello', color: 'flash2', effect: 'wave' })
        expect(parseHeadline('red:Hello')).toEqual({ text: 'Hello', color: 'red' })
        expect(parseHeadline('wave2:Hello')).toEqual({ text: 'Hello', effect: 'wave2' })
    })

    it('leaves plain text, and anything that only looks like flair, as it is', () => {
        expect(parseHeadline('Hello')).toEqual({ text: 'Hello' })
        expect(parseHeadline('wave:red:Hello')).toEqual({ text: 'red:Hello', effect: 'wave' })
        expect(parseHeadline('Note: hello')).toEqual({ text: 'Note: hello' })
    })

    it('leaves every headline some text, with no flair left on it', () => {
        for (const line of HEADLINES) {
            const { text } = parseHeadline(line)
            expect(text).not.toBe('')
            expect(parseHeadline(text)).toEqual({ text })
        }
    })
})
