import { describe, expect, it } from 'vitest'

import { anchorAt, collapse, CONTEXT, locate } from '@/lib/plan-anchors'

const PLAN = 'Add a CSV export.\nThe export streams rows.\n\nTest the export with a large report.'

function quoted(text: string, quote: string, from = 0) {
    const start = text.indexOf(quote, from)
    return anchorAt(text, start, start + quote.length)
}

describe('anchorAt', () => {
    it('keeps the passage and the text either side, whitespace collapsed', () => {
        expect(quoted(PLAN, 'streams rows')).toEqual({
            quote: 'streams rows',
            prefix: 'Add a CSV export. The export',
            suffix: '. Test the export with a large r',
        })
    })

    it('trims whitespace from the selection and refuses one of whitespace alone', () => {
        const start = PLAN.indexOf(' streams')
        expect(anchorAt(PLAN, start, start + 9)?.quote).toBe('streams')
        expect(anchorAt(PLAN, 17, 18)).toBeUndefined()
    })

    it('keeps at most CONTEXT characters either side', () => {
        const long = `${'a'.repeat(100)} middle ${'b'.repeat(100)}`
        const anchor = quoted(long, 'middle')
        expect(anchor?.prefix).toHaveLength(CONTEXT)
        expect(anchor?.suffix).toHaveLength(CONTEXT)
    })
})

describe('locate', () => {
    it('finds a passage again after text above it changed', () => {
        const anchor = quoted(PLAN, 'streams rows')
        if (!anchor) {
            throw new Error('no anchor')
        }
        const edited = `# Plan\n\n${PLAN}`
        const span = locate(edited, anchor)
        expect(span && edited.slice(span.start, span.end)).toBe('streams rows')
    })

    it('tells two copies apart by the text around them', () => {
        const second = PLAN.indexOf('the export', 20)
        const anchor = anchorAt(PLAN, second, second + 'the export'.length)
        if (!anchor) {
            throw new Error('no anchor')
        }
        expect(locate(PLAN, anchor)).toEqual({ start: second, end: second + 'the export'.length })
    })

    it('finds a passage the planner reflowed', () => {
        const anchor = quoted('one two three four', 'two three')
        if (!anchor) {
            throw new Error('no anchor')
        }
        const reflowed = 'one two\n   three four'
        const span = locate(reflowed, anchor)
        expect(span && collapse(reflowed.slice(span.start, span.end))).toBe('two three')
    })

    it('finds nothing for a passage that is gone, rather than something near it', () => {
        const anchor = quoted(PLAN, 'streams rows')
        if (!anchor) {
            throw new Error('no anchor')
        }
        expect(locate(PLAN.replace('streams rows', 'buffers rows'), anchor)).toBeUndefined()
        expect(locate(PLAN, { quote: '', prefix: '', suffix: '' })).toBeUndefined()
    })
})
