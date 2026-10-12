import { describe, expect, it } from 'vitest'

import { phaseLabel } from './phase'

describe('phaseLabel', () => {
    it('prefers the recorded phase, then the last decision', () => {
        expect(phaseLabel({ phase: 'ci_running', last_decision: 'wait' })).toBe('ci_running')
        expect(phaseLabel({ phase: null, last_decision: 'dispatch:implement' })).toBe(
            'not recorded, last decision dispatch:implement',
        )
    })

    it('says a ticket no tick has decided about is not seen yet', () => {
        expect(phaseLabel({ phase: null, last_decision: null })).toBe('not seen by a tick yet')
    })
})
