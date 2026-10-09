import { describe, expect, it } from 'vitest'

import { actionTone } from './decisions'

describe('actionTone', () => {
    it('marks refusals and attention items, and nothing else', () => {
        expect(actionTone('refused:running')).toBe('refused')
        expect(actionTone('attention:worker_failed')).toBe('attention')
        expect(actionTone('dispatch:implement')).toBe('other')
        expect(actionTone('wait')).toBe('other')
        expect(actionTone('mirror')).toBe('other')
    })
})
