import { describe, expect, it } from 'vitest'

import { readable, runKind } from './words'

describe('readable', () => {
    it('spaces a snake_case word', () => {
        expect(readable('awaiting_reply')).toBe('awaiting reply')
        expect(readable('unknown_result')).toBe('unknown result')
    })

    it('spaces after an action prefix', () => {
        expect(readable('attention:needs_reviewer')).toBe('attention: needs reviewer')
        expect(readable('dispatch:resume')).toBe('dispatch: resume')
        expect(readable('refused:running')).toBe('refused: running')
    })

    it('leaves a plain word alone', () => {
        expect(readable('wait')).toBe('wait')
        expect(readable('fix-ci')).toBe('fix-ci')
        expect(readable('tool-calls')).toBe('tool-calls')
    })
})

describe('runKind', () => {
    it("follows a resume's kind with its reasons, as canopy status prints it", () => {
        expect(runKind({ kind: 'resume', reasons: ['ci', 'review'] })).toBe('resume (ci, review)')
    })

    it('is the kind alone for a run without reasons, an old fix-ci among them', () => {
        expect(runKind({ kind: 'implement', reasons: [] })).toBe('implement')
        expect(runKind({ kind: 'fix-ci', reasons: [] })).toBe('fix-ci')
    })
})
