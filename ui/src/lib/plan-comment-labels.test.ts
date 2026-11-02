import { describe, expect, it } from 'vitest'

import { COMMENT_LABELS, withLabel } from '@/lib/plan-comment-labels'
import type { CommentLabel } from '@/lib/plan-comment-labels'

function label(name: string): CommentLabel {
    const found = COMMENT_LABELS.find((each) => each.name === name)
    if (found === undefined) {
        throw new Error(`no label ${name}`)
    }
    return found
}

describe('COMMENT_LABELS', () => {
    it('offers the four labels, each instruction opening with its name, so a card says which it is', () => {
        expect(COMMENT_LABELS.map((each) => each.name)).toEqual([
            'Verify this',
            'Out of scope',
            'Match existing patterns',
            'Needs tests',
        ])
        for (const each of COMMENT_LABELS) {
            expect(each.instruction.startsWith(`${each.name}: `)).toBe(true)
        }
    })

    it('words each as an instruction, never a suggestion the planner may pass over', () => {
        for (const each of COMMENT_LABELS) {
            expect(each.instruction).not.toMatch(/\b(?:maybe|perhaps|consider|might|could you|please)\b/iu)
            expect(each.instruction).toMatch(/[.]$/u)
        }
    })
})

describe('withLabel', () => {
    it('writes the instruction, then an empty paragraph for the operator’s words', () => {
        const verify = label('Verify this')
        expect(withLabel('', verify)).toBe(`${verify.instruction}\n\n`)
    })

    it('puts the instruction before what the operator wrote already, as a paragraph of its own', () => {
        const tests = label('Needs tests')
        expect(withLabel('  Cover the empty report.', tests)).toBe(`${tests.instruction}\n\nCover the empty report.`)
    })

    it('changes the label rather than stacking a second, keeping the operator’s words', () => {
        const scope = label('Out of scope')
        const patterns = label('Match existing patterns')
        const once = withLabel('The CSV writer.', scope)
        expect(withLabel(once, patterns)).toBe(`${patterns.instruction}\n\nThe CSV writer.`)
        expect(withLabel(withLabel('', scope), scope)).toBe(`${scope.instruction}\n\n`)
    })
})
