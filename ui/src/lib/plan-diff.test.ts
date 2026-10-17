import { Editor } from '@tiptap/core'
import { describe, expect, it } from 'vitest'

import { changesKey, diffWords, PlanChanges, textOf } from '@/lib/plan-diff'
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

    it('past its cap, shows the part that differs as removed and added whole', () => {
        const changes = diffWords('a b c d', 'w x y z', 2)
        expect(changes.map((change) => change.kind)).toEqual(['del', 'add'])
        expect(after(changes)).toBe('w x y z')
    })
})

describe('PlanChanges', () => {
    it("draws the new plan's added words and the old plan's removed ones, and nothing once told to stop", () => {
        const editor = new Editor({
            extensions: planExtensions([PlanChanges]),
            content: '# Plan\n\nStream the rows to the client.',
            contentType: 'markdown',
        })
        const base = textOf(editor, '# Plan\n\nStream the rows to a file.')
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
})
