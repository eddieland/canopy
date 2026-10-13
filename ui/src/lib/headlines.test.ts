import { describe, expect, it } from 'vitest'

import { HEADLINES, headlinesFor, parseHeadline, REEL, TICKER_TOPICS } from './headlines'

const ALL = TICKER_TOPICS.flatMap((topic) => HEADLINES[topic])

describe('headlinesFor', () => {
    const day = 86_400_000
    const now = Date.parse('2026-10-08T12:30:00Z')

    it('lists every headline once', () => {
        expect([...headlinesFor(now)].toSorted()).toEqual([...ALL].toSorted())
    })

    it("leaves out the hidden topics, and keeps the rest in the reel's order", () => {
        const jokes = headlinesFor(now, ['tips'])
        expect(jokes.toSorted()).toEqual([...HEADLINES.programming, ...HEADLINES.vibes].toSorted())
        expect(jokes).toEqual(headlinesFor(now).filter((line) => !HEADLINES.tips.includes(line)))
        expect(headlinesFor(now, [...TICKER_TOPICS])).toEqual([])
    })

    it('keeps one lead all day and moves to the next one the day after', () => {
        const lead = headlinesFor(now)[0]
        const start = Math.floor(now / day) * day
        expect(headlinesFor(start)[0]).toBe(lead)
        expect(headlinesFor(start + day - 1)[0]).toBe(lead)
        expect(headlinesFor(start + day)[0]).toBe(headlinesFor(now)[1])
    })

    it('has no two headlines alike, since each is its own key', () => {
        expect(new Set(ALL).size).toBe(ALL.length)
    })
})

describe('REEL', () => {
    it('mixes the tips in among the jokes, never two in a row', () => {
        const tips = REEL.map(({ topic }) => topic === 'tips')
        expect(tips.some((tip, i) => tip && tips[i + 1])).toBe(false)
        expect(REEL.slice(0, 10).some(({ topic }) => topic === 'tips')).toBe(true)
    })

    it("keeps each topic's headlines in their order", () => {
        for (const topic of TICKER_TOPICS) {
            expect(REEL.filter((entry) => entry.topic === topic).map(({ line }) => line)).toEqual(HEADLINES[topic])
        }
    })

    it('opens every tip with "Tip: " and no joke with it', () => {
        for (const { topic, line } of REEL) expect(line.startsWith('Tip: ')).toBe(topic === 'tips')
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
