import { describe, expect, it } from 'vitest'

import { phaseLabel, phaseWord } from './phase'

describe('phaseLabel', () => {
    it('prefers the recorded phase, then the last decision, each read as words', () => {
        expect(phaseLabel({ phase: 'ci_running', last_decision: 'wait' })).toBe('ci running')
        expect(phaseLabel({ phase: null, last_decision: 'attention:needs_human' })).toBe(
            'not recorded, last decision attention: needs human',
        )
    })

    it('says a ticket no tick has decided about is not seen yet', () => {
        expect(phaseLabel({ phase: null, last_decision: null })).toBe('not seen by a tick yet')
    })
})

describe('phaseWord', () => {
    it('keeps the journal words as the CLI prints them, for the hover', () => {
        expect(phaseWord({ phase: 'ci_running', last_decision: 'wait' })).toBe('ci_running')
        expect(phaseWord({ phase: null, last_decision: 'attention:needs_human' })).toBe(
            'not recorded, last decision attention:needs_human',
        )
    })
})
