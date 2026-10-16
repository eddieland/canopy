import { describe, expect, it } from 'vitest'

import { actionTone } from './decisions'

describe('actionTone', () => {
    it('marks refusals and attention items, and nothing else', () => {
        expect(actionTone('refused:running')).toBe('failed')
        expect(actionTone('attention:worker_failed')).toBe('blocked')
        expect(actionTone('dispatch:implement')).toBe('plain')
        expect(actionTone('wait')).toBe('plain')
        expect(actionTone('mirror')).toBe('plain')
    })
})
