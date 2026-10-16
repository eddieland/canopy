import { Editor } from '@tiptap/core'
import { afterEach, describe, expect, it } from 'vitest'

import { anchorFor, anchorsOf, highlightsKey, PlanHighlights, withHighlight } from '@/lib/plan-highlights'
import type { Placed } from '@/lib/plan-highlights'
import { planExtensions } from '@/lib/plan-schema'

const editors: Editor[] = []

function open(markdown: string): Editor {
    const editor = new Editor({
        extensions: planExtensions([PlanHighlights]),
        content: markdown,
        contentType: 'markdown',
    })
    editors.push(editor)
    return editor
}

afterEach(() => {
    for (const editor of editors.splice(0)) {
        editor.destroy()
    }
})

const PLAN = '# Plan\n\nStream the rows.\n\nTest with a large report.'

function placed(id: string, quote: string, resolved = false): Placed {
    return { id, anchor: { quote, prefix: '', suffix: '' }, resolved }
}

function sync(editor: Editor, threads: Placed[]) {
    editor.view.dispatch(withHighlight(editor.state.tr, { kind: 'sync', threads }))
}

function quoteOf(editor: Editor, id: string) {
    const range = highlightsKey.getState(editor.state)?.ranges.get(id)
    return range && editor.state.doc.textBetween(range.from, range.to)
}

describe('PlanHighlights', () => {
    it('finds each thread by its anchor and draws the open ones', () => {
        const editor = open(PLAN)
        sync(editor, [placed('a', 'the rows'), placed('b', 'large report', true), placed('c', 'nowhere')])
        expect(quoteOf(editor, 'a')).toBe('the rows')
        expect(quoteOf(editor, 'b')).toBe('large report')
        expect(quoteOf(editor, 'c')).toBeUndefined()
        expect(highlightsKey.getState(editor.state)?.decorations.find()).toHaveLength(1)
    })

    it('keeps a passage through edits around it, and the anchor follows', () => {
        const editor = open(PLAN)
        sync(editor, [placed('a', 'the rows')])
        editor.commands.insertContentAt(1, 'New ')
        expect(quoteOf(editor, 'a')).toBe('the rows')
        const range = highlightsKey.getState(editor.state)?.ranges.get('a')
        if (!range) {
            throw new Error('no range')
        }
        // Typing inside the passage changes its words.
        editor.commands.insertContentAt(range.from + 3, ' raw')
        const { anchors, starts } = anchorsOf(editor.state)
        expect(anchors.get('a')?.quote).toBe('the raw rows')
        expect(starts.get('a')).toBe(range.from)
    })

    it('loses a passage deleted whole, and finds it again on undo', () => {
        const editor = open(PLAN)
        sync(editor, [placed('a', 'the rows')])
        const range = highlightsKey.getState(editor.state)?.ranges.get('a')
        if (!range) {
            throw new Error('no range')
        }
        editor.commands.deleteRange(range)
        expect(quoteOf(editor, 'a')).toBeUndefined()
        expect(anchorsOf(editor.state).anchors.has('a')).toBe(false)
        editor.commands.undo()
        expect(quoteOf(editor, 'a')).toBe('the rows')
    })

    it('adds a thread at the selection, and drops one no longer synced', () => {
        const editor = open(PLAN)
        const text = editor.state.doc.textContent
        const from = 1 + text.indexOf('Stream') + 2
        const anchor = anchorFor(editor.state, from, from + 6)
        expect(anchor?.quote).toBe('Stream')
        editor.view.dispatch(withHighlight(editor.state.tr, { kind: 'add', id: 'n', range: { from, to: from + 6 } }))
        expect(quoteOf(editor, 'n')).toBe('Stream')
        expect(highlightsKey.getState(editor.state)?.active).toBe('n')
        sync(editor, [])
        expect(quoteOf(editor, 'n')).toBeUndefined()
    })

    it('asks for a comment on Mod+Alt+M, through the editor’s events', () => {
        const editor = open(PLAN)
        let asked = 0
        editor.on('planCommentRequest', () => {
            asked += 1
        })
        editor.commands.keyboardShortcut('Mod-Alt-m')
        expect(asked).toBe(1)
    })
})
