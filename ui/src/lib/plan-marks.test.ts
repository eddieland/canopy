import { Editor } from '@tiptap/core'
import { afterEach, describe, expect, it } from 'vitest'

import { MARKS_MAX, marksOn, parseMarks, planSections, withMark } from '@/lib/plan-marks'
import type { PlanMarks, PlanSection } from '@/lib/plan-marks'
import { planExtensions } from '@/lib/plan-schema'

const PLAN = [
    '# Plan: ABC-1 Export',
    '## Goal',
    'Export reports.',
    '## Steps',
    '### Step 1: the route',
    'Add it.',
    '## Risks',
    'None.',
].join('\n\n')
const AT = '2026-10-08T12:00:00Z'

const editors: Editor[] = []

function sections(markdown: string): PlanSection[] {
    const editor = new Editor({ extensions: planExtensions(), content: markdown, contentType: 'markdown' })
    editors.push(editor)
    return planSections(editor.state.doc)
}

function section(markdown: string, key: string): PlanSection {
    const found = sections(markdown).find((s) => s.key === key)
    if (found === undefined) {
        throw new Error(`no section ${key}`)
    }
    return found
}

afterEach(() => {
    for (const editor of editors.splice(0)) {
        editor.destroy()
    }
})

describe('planSections', () => {
    it("lists a plan's `##` sections, each holding what is under it to the next, its steps included", () => {
        const found = sections(PLAN)
        expect(found.map((s) => s.key)).toEqual(['Goal', 'Steps', 'Risks'])
        const edited = sections(PLAN.replace('Add it.', 'Add the route.'))
        expect(edited.map((s) => s.digest === found.find((f) => f.key === s.key)?.digest)).toEqual([true, false, true])
    })

    it('tells two sections of the same heading apart, and leaves out one with no words', () => {
        expect(sections('## Notes\n\nA.\n\n##\n\n## Notes\n\nB.').map((s) => s.key)).toEqual(['Notes', 'Notes #2'])
    })

    it('ends a section at a `#` heading, which is no section of its own', () => {
        const before = section('## Goal\n\nExport.\n\n# Appendix\n\nMore.', 'Goal')
        expect(section('## Goal\n\nExport.\n\n# Appendix\n\nOther.', 'Goal').digest).toBe(before.digest)
        expect(sections('# Appendix\n\nMore.')).toEqual([])
    })
})

describe('marks', () => {
    it('holds a mark while its section reads as it did when marked, as a new plan that left it so does', () => {
        const goal = section(PLAN, 'Goal')
        const marks = withMark({}, 'ABC-1', goal, 'read', AT)
        expect(marksOn(marks['ABC-1'], sections(PLAN))).toEqual(new Map([['Goal', 'read']]))
        expect(marksOn(marks['ABC-1'], sections(PLAN.replace('Add it.', 'Add the route.')))).toEqual(
            new Map([['Goal', 'read']]),
        )
        expect(marksOn(marks['ABC-1'], sections(PLAN.replace('Export reports.', 'Export CSV.')))).toEqual(new Map())
    })

    it('keeps one mark a section, cleared with none, and drops a ticket left with none', () => {
        const goal = section(PLAN, 'Goal')
        const read = withMark({}, 'ABC-1', goal, 'read', AT)
        const concern = withMark(read, 'ABC-1', goal, 'concern', AT)
        expect(marksOn(concern['ABC-1'], [goal])).toEqual(new Map([['Goal', 'concern']]))
        expect(withMark(concern, 'ABC-1', goal, undefined, AT)).toEqual({})
    })

    it('keeps the tickets marked last, at most MARKS_MAX', () => {
        const goal = section(PLAN, 'Goal')
        let marks: PlanMarks = {}
        for (let i = 0; i <= MARKS_MAX; i += 1) {
            marks = withMark(marks, `ABC-${i}`, goal, 'read', new Date(Date.parse(AT) + i * 1000).toISOString())
        }
        expect(Object.keys(marks)).toHaveLength(MARKS_MAX)
        expect(marks['ABC-0']).toBeUndefined()
        expect(marks[`ABC-${MARKS_MAX}`]).toBeDefined()
    })

    it('reads what is stored, dropping whatever is not a ticket or a mark', () => {
        const stored = {
            'ABC-1': { at: AT, sections: { Goal: { mark: 'read', digest: 'x' }, Risks: { mark: 'meh', digest: 'y' } } },
            'ABC-2': { sections: {} },
        }
        expect(parseMarks(JSON.stringify(stored))).toEqual({
            'ABC-1': { at: AT, sections: { Goal: { mark: 'read', digest: 'x' } } },
        })
        expect(parseMarks(null)).toEqual({})
        expect(parseMarks('[1]')).toEqual({})
        expect(parseMarks('{')).toEqual({})
    })
})
