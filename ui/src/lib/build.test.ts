import { describe, expect, it } from 'vitest'

import { buildIn, isOutdated } from './build'

describe('buildIn', () => {
    it('reads the build id from the meta tag, and null without one', () => {
        const doc = document.implementation.createHTMLDocument()
        expect(buildIn(doc)).toBeNull()
        const meta = doc.createElement('meta')
        meta.name = 'canopy-build'
        meta.content = 'abc123'
        doc.head.append(meta)
        expect(buildIn(doc)).toBe('abc123')
        meta.content = ''
        expect(buildIn(doc)).toBeNull()
    })
})

describe('isOutdated', () => {
    it('is true only when the server serves another build than the page loaded', () => {
        expect(isOutdated('abc', 'def')).toBe(true)
        expect(isOutdated('abc', 'abc')).toBe(false)
    })

    it('is false when either build is unknown', () => {
        expect(isOutdated(null, 'def')).toBe(false)
        expect(isOutdated('abc', null)).toBe(false)
        expect(isOutdated('abc', undefined)).toBe(false)
    })
})
