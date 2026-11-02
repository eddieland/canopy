import { Editor } from '@tiptap/core'
import { afterEach, describe, expect, it } from 'vitest'

import { planOutline, sectionAt } from '@/lib/plan-outline'
import { planExtensions } from '@/lib/plan-schema'

const editors: Editor[] = []

function outline(markdown: string) {
    const editor = new Editor({ extensions: planExtensions(), content: markdown, contentType: 'markdown' })
    editors.push(editor)
    return planOutline(editor.state.doc).map(({ level, depth, text }) => ({ level, depth, text }))
}

afterEach(() => {
    for (const editor of editors.splice(0)) {
        editor.destroy()
    }
})

describe('planOutline', () => {
    it("lists a plan's headings in order, each indented under the shallowest", () => {
        const plan = '# Plan: ABC-1 Export\n\n## Goal\n\nExport.\n\n## Steps\n\n### Step 1: the route\n\nAdd it.'
        expect(outline(plan)).toEqual([
            { level: 1, depth: 0, text: 'Plan: ABC-1 Export' },
            { level: 2, depth: 1, text: 'Goal' },
            { level: 2, depth: 1, text: 'Steps' },
            { level: 3, depth: 2, text: 'Step 1: the route' },
        ])
    })

    it('lists a decision as a step is listed, a level under its section, and never among the steps', () => {
        const plan = '# Plan\n\n## Decisions\n\n### Decision 1: the encoding\n\n## Steps\n\n### Step 1: the route\n'
        expect(outline(plan)).toEqual([
            { level: 1, depth: 0, text: 'Plan' },
            { level: 2, depth: 1, text: 'Decisions' },
            { level: 3, depth: 2, text: 'Decision 1: the encoding' },
            { level: 2, depth: 1, text: 'Steps' },
            { level: 3, depth: 2, text: 'Step 1: the route' },
        ])
    })

    it('indents from the shallowest heading the plan has, not from a `#`', () => {
        expect(outline('## Goal\n\n### Step 1\n\n## Risks')).toEqual([
            { level: 2, depth: 0, text: 'Goal' },
            { level: 3, depth: 1, text: 'Step 1' },
            { level: 2, depth: 0, text: 'Risks' },
        ])
    })

    it('leaves out a heading with no words and one inside a quote', () => {
        expect(outline('## Goal\n\n##\n\n> ## Quoted\n\n## Risks').map((entry) => entry.text)).toEqual([
            'Goal',
            'Risks',
        ])
    })

    it('finds each heading where the document holds it', () => {
        const editor = new Editor({
            extensions: planExtensions(),
            content: '## Goal\n\nText.\n\n## Risks',
            contentType: 'markdown',
        })
        editors.push(editor)
        const entries = planOutline(editor.state.doc)
        expect(entries).toHaveLength(2)
        for (const entry of entries) {
            expect(editor.state.doc.nodeAt(entry.pos)?.textContent).toBe(entry.text)
        }
    })

    it('is empty for a plan with no headings', () => {
        expect(outline('Just a paragraph.')).toEqual([])
    })
})

describe('sectionAt', () => {
    it('is the last heading at or above the line', () => {
        expect(sectionAt([0, 100, 200], 150)).toBe(1)
        expect(sectionAt([0, 100, 200], 200)).toBe(2)
    })

    it('is the first while every heading is below the line, and none without headings', () => {
        expect(sectionAt([300, 400], 80)).toBe(0)
        expect(sectionAt([], 80)).toBeUndefined()
    })
})
