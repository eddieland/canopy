import { describe, expect, it } from 'vitest'

import { HEADLINES, headlinesFor, nextIndex, parseHeadline, TICKER_TOPICS } from './headlines'

const ALL = TICKER_TOPICS.flatMap((topic) => HEADLINES[topic])

describe('headlinesFor', () => {
    it('lists every headline once', () => {
        expect(headlinesFor().toSorted()).toEqual([...ALL].toSorted())
    })

    it('leaves out the hidden topics', () => {
        expect(headlinesFor(['tips'])).toEqual([...HEADLINES.programming, ...HEADLINES.vibes])
        expect(headlinesFor([...TICKER_TOPICS])).toEqual([])
    })

    it('has no two headlines alike, since each is its own key', () => {
        expect(new Set(ALL).size).toBe(ALL.length)
    })

    it('opens every tip with "Tip: " and no joke with it', () => {
        for (const topic of TICKER_TOPICS) {
            for (const line of HEADLINES[topic]) expect(line.startsWith('Tip: ')).toBe(topic === 'tips')
        }
    })
})

describe('nextIndex', () => {
    it('never picks the last one while there is another', () => {
        const rolls = [0, 0.25, 0.5, 0.75, 0.9999]
        for (const roll of rolls) expect(nextIndex(4, 2, () => roll)).not.toBe(2)
        expect(rolls.map((roll) => nextIndex(4, 2, () => roll))).toEqual([0, 0, 1, 3, 3])
        expect(nextIndex(4, 0, () => 0)).toBe(1)
    })

    it('picks from them all with no last in range, and the only one when there is one', () => {
        expect(nextIndex(4, -1, () => 0)).toBe(0)
        expect(nextIndex(4, -1, () => 0.9999)).toBe(3)
        expect(nextIndex(4, 7, () => 0.5)).toBe(2)
        expect(nextIndex(1, 0, () => 0.5)).toBe(0)
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
        for (const line of ALL) {
            const { text } = parseHeadline(line)
            expect(text).not.toBe('')
            expect(parseHeadline(text)).toEqual({ text })
        }
    })
})
