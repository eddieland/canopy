import { describe, expect, it } from 'vitest'

import { isBlank } from './utils'

describe('isBlank', () => {
    it('is true for what React renders as nothing, and false for anything it shows', () => {
        for (const node of [null, undefined, false, true, '']) {
            expect(isBlank(node)).toBe(true)
        }
        for (const node of ['text', 0, ['a']]) {
            expect(isBlank(node)).toBe(false)
        }
    })
})
