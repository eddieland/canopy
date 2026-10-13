import { describe, expect, it } from 'vitest'

import { readable } from './words'

describe('readable', () => {
    it('spaces a snake_case word', () => {
        expect(readable('awaiting_reply')).toBe('awaiting reply')
        expect(readable('unknown_result')).toBe('unknown result')
    })

    it('spaces after an action prefix', () => {
        expect(readable('attention:needs_reviewer')).toBe('attention: needs reviewer')
        expect(readable('dispatch:fix-ci')).toBe('dispatch: fix-ci')
        expect(readable('refused:running')).toBe('refused: running')
    })

    it('leaves a plain word alone', () => {
        expect(readable('wait')).toBe('wait')
        expect(readable('fix-ci')).toBe('fix-ci')
        expect(readable('tool-calls')).toBe('tool-calls')
    })
})
