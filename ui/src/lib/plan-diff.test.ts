import { Editor } from '@tiptap/core'
import { describe, expect, it } from 'vitest'

import { changesKey, diffPlans, diffWords, outlineOf, PlanChanges } from '@/lib/plan-diff'
import type { Change } from '@/lib/plan-diff'
import { planExtensions } from '@/lib/plan-schema'

// The text a diff's runs make, with the removed runs left out: the new text, if the runs are right.
function after(changes: Change[]): string {
    return changes
        .filter((change) => change.kind !== 'del')
        .map((change) => change.text)
        .join('')
}

describe('diffWords', () => {
    it('finds the words added and removed, each where it is in the new text', () => {
        const changes = diffWords('Stream the rows to a file.', 'Stream the rows to the client.')
        expect(changes).toEqual([
            { kind: 'same', text: 'Stream the rows to ', at: 0 },
            { kind: 'del', text: 'a file', at: 19 },
            { kind: 'add', text: 'the client', at: 19 },
            { kind: 'same', text: '.', at: 29 },
        ])
        expect(after(changes)).toBe('Stream the rows to the client.')
    })

    it('says nothing changed for the same text, and everything for text with nothing in common', () => {
        expect(diffWords('Same plan.', 'Same plan.')).toEqual([{ kind: 'same', text: 'Same plan.', at: 0 }])
        expect(diffWords('', 'New plan.')).toEqual([{ kind: 'add', text: 'New plan.', at: 0 }])
        expect(diffWords('Old plan.', '')).toEqual([{ kind: 'del', text: 'Old plan.', at: 0 }])
    })

    it('keeps the words around changes far apart, and puts each change at its place', () => {
        const before = 'one two three four five six seven eight nine ten'
        const now = 'one 2 three four five six seven eight nine 10'
        const changes = diffWords(before, now)
        expect(after(changes)).toBe(now)
        expect(changes.filter((change) => change.kind === 'add')).toEqual([
            { kind: 'add', text: '2 ', at: 4 },
            { kind: 'add', text: '10', at: now.indexOf('10') },
        ])
    })

    it('takes a word that ended a sentence and now goes on as the same word, not removed and added again', () => {
        const now = 'Daily, at an hour the operator picks.'
        const changes = diffWords('Daily, at an hour.', now)
        expect(changes.filter((change) => change.kind !== 'same')).toEqual([
            { kind: 'add', text: 'the operator picks', at: now.indexOf('the') },
        ])
        expect(after(changes)).toBe(now)
    })

    it('past its cap, shows the part that differs as removed and added whole', () => {
        const changes = diffWords('a b c d', 'w x y z', 2)
        expect(changes.map((change) => change.kind)).toEqual(['del', 'add'])
        expect(after(changes)).toBe('w x y z')
    })
})

// The changes a diff holds, without the words kept.
function edits(changes: Change[]): Change[] {
    return changes.filter((change) => change.kind !== 'same')
}

describe('diffPlans', () => {
    const editor = new Editor({ extensions: planExtensions([PlanChanges]), content: '' })
    const outline = (markdown: string) => outlineOf(editor, markdown)
    const PLAN = '# Export\n\n## Goal\n\nShip the export.\n\n## Steps\n\nStream the rows.\n\n## Risks\n\nLarge tables.'

    it('says a section that moved moved, the fewest that put the rest in order, and changed no word', () => {
        const now = outline(
            '# Export\n\n## Risks\n\nLarge tables.\n\n## Goal\n\nShip the export.\n\n## Steps\n\nStream the rows.',
        )
        const diff = diffPlans(outline(PLAN), now)
        expect(edits(diff.changes)).toEqual([])
        expect(diff.moved.map((at) => now.text.slice(at, at + 5))).toEqual(['Risks'])
        expect(diff.removed).toEqual([])
    })

    it('folds a section dropped into one removal where the section after it now is, not struck words', () => {
        const now = outline('# Export\n\n## Goal\n\nShip the export.\n\n## Risks\n\nLarge tables.')
        const diff = diffPlans(outline(PLAN), now)
        expect(edits(diff.changes)).toEqual([])
        expect(diff.removed).toEqual([{ at: now.text.indexOf('Risks'), heading: 'Steps', body: 'Stream the rows.' }])
        // One dropped from the end is removed at the end.
        const end = diffPlans(
            outline(PLAN),
            outline('# Export\n\n## Goal\n\nShip the export.\n\n## Steps\n\nStream the rows.'),
        )
        expect(end.removed.map(({ heading }) => heading)).toEqual(['Risks'])
        expect(end.removed[0]?.at).toBe(
            outline('# Export\n\n## Goal\n\nShip the export.\n\n## Steps\n\nStream the rows.').text.length,
        )
    })

    it('pairs a section renamed by its words, and one under a renamed heading by its own', () => {
        const renamed = diffPlans(outline(PLAN), outline(PLAN.replace('## Steps', '## How')))
        expect(edits(renamed.changes).map((change) => [change.kind, change.text.trim()])).toEqual([
            ['del', 'Steps'],
            ['add', 'How'],
        ])
        expect(renamed.removed).toEqual([])
        const retitled = diffPlans(outline(PLAN), outline(PLAN.replace('# Export', '# Export as CSV')))
        expect(edits(retitled.changes).map((change) => change.text.trim())).toEqual(['as CSV'])
        expect(retitled.moved).toEqual([])
        // One rewritten with its heading, sharing too few words to pair by, still pairs by where it is.
        const rewritten = diffPlans(
            outline(PLAN),
            outline(PLAN.replace('## Risks\n\nLarge tables.', '## Dangers\n\nHuge exports.')),
        )
        expect(rewritten.removed).toEqual([])
        expect(edits(rewritten.changes).map((change) => change.kind)).toEqual(['del', 'add', 'del', 'add'])
    })

    it('adds a section with no pair whole, and compares the words of the sections it pairs', () => {
        const now = outline(
            `${PLAN.replace('Stream the rows.', 'Stream the rows to the client.')}\n\n## Tests\n\nOne row.`,
        )
        const diff = diffPlans(outline(PLAN), now)
        expect(edits(diff.changes).map((change) => [change.kind, change.text.trim()])).toEqual([
            ['add', 'to the client'],
            ['add', 'Tests\nOne row.'],
        ])
    })
})

describe('PlanChanges', () => {
    it("draws the new plan's added words and the old plan's removed ones, and nothing once told to stop", () => {
        const editor = new Editor({
            extensions: planExtensions([PlanChanges]),
            content: '# Plan\n\nStream the rows to the client.',
            contentType: 'markdown',
        })
        const base = outlineOf(editor, '# Plan\n\nStream the rows to a file.')
        editor.view.dispatch(editor.state.tr.setMeta(changesKey, { base }))
        const added = [...editor.view.dom.querySelectorAll('ins.plan-ins')].map((node) => node.textContent)
        const removed = [...editor.view.dom.querySelectorAll('del.plan-del')].map((node) => node.textContent)
        expect(added).toEqual(['the client'])
        expect(removed).toEqual(['a file'])
        // A removal and the words that replaced it are one change, where they start.
        const starts = changesKey.getState(editor.state)?.starts ?? []
        expect(starts).toHaveLength(1)
        expect(editor.state.doc.textBetween(starts[0] ?? 0, (starts[0] ?? 0) + 'the client'.length)).toBe('the client')
        editor.commands.insertContentAt(editor.state.doc.content.size - 1, ' Then close it.')
        expect(editor.view.dom.querySelector('ins.plan-ins:last-of-type')?.textContent).toContain('Then close it')
        editor.view.dispatch(editor.state.tr.setMeta(changesKey, { base: undefined }))
        expect(editor.view.dom.querySelectorAll('ins.plan-ins, del.plan-del')).toHaveLength(0)
        expect(changesKey.getState(editor.state)?.starts).toEqual([])
        editor.destroy()
    })

    it('marks a block added whole as one, not as words, and the words added to an old block as words', () => {
        const editor = new Editor({
            extensions: planExtensions([PlanChanges]),
            content: '# Plan\n\nStream the rows to the client.\n\n## Risks\n\nA `job` may **fail** twice.',
            contentType: 'markdown',
        })
        const base = outlineOf(editor, '# Plan\n\nStream the rows.')
        editor.view.dispatch(editor.state.tr.setMeta(changesKey, { base }))
        const blocks = [...editor.view.dom.querySelectorAll('.plan-block-add')].map((node) => node.textContent)
        expect(blocks).toEqual(['Risks', 'A job may fail twice.'])
        // The new section is compared with none of the old one's, so the old paragraph keeps its stop.
        const added = [...editor.view.dom.querySelectorAll('ins.plan-ins')].map((node) => node.textContent)
        expect(added).toEqual(['to the client'])
        // The words added to the old paragraph are one change, and the section added whole another.
        expect(changesKey.getState(editor.state)?.starts).toHaveLength(2)
        editor.destroy()
    })

    it('marks a section that moved at its heading, and folds one removed where it was, its words struck inside', () => {
        const editor = new Editor({
            extensions: planExtensions([PlanChanges]),
            content: '# Plan\n\n## Risks\n\nA job may fail.\n\n## Steps\n\nStream the rows.\n\n## Tests\n\nOne row.',
            contentType: 'markdown',
        })
        const base = outlineOf(
            editor,
            '# Plan\n\n## Steps\n\nStream the rows.\n\n## Notes\n\nAsk ops.\n\n' +
                '## Tests\n\nOne row.\n\n## Risks\n\nA job may fail.',
        )
        editor.view.dispatch(editor.state.tr.setMeta(changesKey, { base }))
        const moved = [...editor.view.dom.querySelectorAll('.plan-moved')].map(
            (node) => node.parentElement?.textContent,
        )
        expect(moved).toEqual(['Risksmoved'])
        const removed = [...editor.view.dom.querySelectorAll('details.plan-section-del')]
        expect(removed.map((node) => node.querySelector('summary')?.textContent)).toEqual(['Section removed: Notes'])
        expect(removed[0]?.querySelector('del')?.textContent).toBe('Ask ops.')
        // Where it was: before the section that came after it then, and still does.
        expect(removed[0]?.nextElementSibling?.textContent).toBe('Tests')
        // No word of it is marked as words.
        const marks = [...editor.view.dom.querySelectorAll('ins.plan-ins, del.plan-del, .plan-block-add')]
        expect(marks.filter((node) => node.closest('details') === null)).toHaveLength(0)
        expect(changesKey.getState(editor.state)?.starts).toHaveLength(2)
        editor.destroy()
    })

    it("marks a table's cell added whole as the cell", () => {
        const editor = new Editor({
            extensions: planExtensions([PlanChanges]),
            content: '# Plan\n\n| File | Why |\n| --- | --- |\n| `job.py` | the job |\n| `menu.py` | the menu |',
            contentType: 'markdown',
        })
        const base = outlineOf(editor, '# Plan\n\n| File | Why |\n| --- | --- |\n| `job.py` | the job |')
        editor.view.dispatch(editor.state.tr.setMeta(changesKey, { base }))
        const cells = [...editor.view.dom.querySelectorAll('.plan-cell-add')]
        expect(cells.map((node) => [node.nodeName, node.textContent])).toEqual([
            ['TD', 'menu.py'],
            ['TD', 'the menu'],
        ])
        expect(editor.view.dom.querySelectorAll('ins.plan-ins, .plan-block-add')).toHaveLength(0)
        editor.destroy()
    })
})
