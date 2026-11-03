import { describe, expect, it } from 'vitest'

import { BURST_WORDS, burstWord } from './burst'

describe('burstWord', () => {
    it('makes the same sound for the same item', () => {
        expect(burstWord('awaiting_reply:ABC-102')).toBe(burstWord('awaiting_reply:ABC-102'))
    })

    it('letters one of its sound effects, and not always the same one', () => {
        const words = new Set(Array.from({ length: 40 }, (_, n) => burstWord(`item-${n}`)))
        expect([...words].every((word) => (BURST_WORDS as readonly string[]).includes(word))).toBe(true)
        expect(words.size).toBeGreaterThan(3)
    })

    it('never letters a verdict', () => {
        expect(BURST_WORDS.filter((word) => /\b(?:DONE|OK|FAIL|PASS|ERROR)\b/u.test(word))).toEqual([])
    })
})
