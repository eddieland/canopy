import { describe, expect, it } from 'vitest'

import { mockAttention } from '@/api/mocks'
import type { AttentionItem } from '@/api/types'

import { faviconDot, faviconSvg, faviconUrl } from './favicon'
import type { FaviconColors } from './favicon'
import staticIcon from '../../public/favicon.svg?raw'

const WAITING = mockAttention[0] as AttentionItem
const FAILED: AttentionItem = { ...WAITING, id: 'a2', reason: 'worker_failed' }
const OTHER: AttentionItem = { ...WAITING, id: 'a3', reason: 'needs_human' }
const PARKED: AttentionItem = { ...WAITING, id: 'a4', reason: 'needs_reviewer' }
const FINDING: AttentionItem = { ...WAITING, id: 'a5', reason: 'finding', finding: true, ticket_key: null }

// Names, not colors: the icon puts whatever it is given where a color goes.
const COLORS: FaviconColors = { mark: 'MARK', dot: { failed: 'FAILED', waiting: 'WAITING', other: 'OTHER' } }

describe('faviconDot', () => {
    it("is the most severe blocking item's severity", () => {
        expect(faviconDot([OTHER, WAITING, FAILED])).toBe('failed')
        expect(faviconDot([OTHER, WAITING])).toBe('waiting')
        expect(faviconDot([OTHER])).toBe('other')
    })

    it("wears the amber of what waits on you for a running run's question, as for any question", () => {
        const asking: AttentionItem = { ...WAITING, id: 'a6', reason: 'run_question', run: 41 }
        expect(faviconDot([OTHER, asking])).toBe('waiting')
    })

    it('is null for what the tab does not count: a PR waiting on someone else, a finding', () => {
        expect(faviconDot([PARKED, FINDING])).toBeNull()
        expect(faviconDot([PARKED, OTHER])).toBe('other')
    })

    it('is null for an empty list, or one not read yet', () => {
        expect(faviconDot([])).toBeNull()
        expect(faviconDot(undefined)).toBeNull()
    })
})

describe('faviconSvg', () => {
    it('is the mark alone when nothing blocks', () => {
        const svg = faviconSvg(null, COLORS)
        expect(svg).toContain('stroke="MARK"')
        expect(svg).not.toContain('mask')
        expect(svg).not.toMatch(/FAILED|WAITING|OTHER/u)
    })

    it("puts a dot in the severity's color on the corner, cut out of the ring", () => {
        const svg = faviconSvg('waiting', COLORS)
        expect(svg).toContain('fill="WAITING"')
        expect(svg).toContain('mask="url(#m)"')
        expect(svg).not.toMatch(/FAILED|OTHER/u)
    })
})

describe('faviconUrl', () => {
    it('is the SVG as a data URL', () => {
        const url = faviconUrl('failed', COLORS)
        expect(url.startsWith('data:image/svg+xml,')).toBe(true)
        expect(decodeURIComponent(url.slice('data:image/svg+xml,'.length))).toBe(faviconSvg('failed', COLORS))
    })
})

describe('public/favicon.svg', () => {
    it('is well-formed XML, which a double hyphen in a comment breaks, and the icon with it', () => {
        const doc = new DOMParser().parseFromString(staticIcon, 'image/svg+xml')
        expect(doc.querySelector('parsererror')).toBeNull()
        for (const [, comment] of staticIcon.matchAll(/<!--([\s\S]*?)-->/gu)) {
            expect(comment).not.toContain('--')
        }
    })
})
