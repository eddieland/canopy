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

// Presses `key` in the editor as the browser would send it: `commands.keyboardShortcut` keeps only the steps of what
// a handler dispatches, not its meta. Whether a handler took it.
function press(editor: Editor, key: string): boolean {
    const event = new KeyboardEvent('keydown', { key })
    return editor.view.someProp('handleKeyDown', (handle) => handle(editor.view, event)) ?? false
}

// The document position of the first letter of `word`'s `nth` copy, counting text nodes, the first by default.
function posOf(editor: Editor, word: string, nth = 1): number {
    let found: number | undefined
    let seen = 0
    editor.state.doc.descendants((node, pos) => {
        const at = node.isText ? (node.text?.indexOf(word) ?? -1) : -1
        if (found === undefined && at >= 0) {
            seen += 1
            found = seen === nth ? pos + at : undefined
        }
    })
    if (found === undefined) {
        throw new Error(`no ${word} in the plan`)
    }
    return found
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

    it('finds an open thread on its passage reworded, and a resolved one only on its exact words', () => {
        const editor = open(PLAN)
        const from = posOf(editor, 'Test')
        const anchor = anchorFor(editor.state, from, from + 'Test with a large report'.length)
        if (!anchor) {
            throw new Error('no anchor')
        }
        sync(editor, [
            { id: 'open', anchor, resolved: false },
            { id: 'done', anchor, resolved: true },
        ])
        // As the Markdown mode reads its text back: the whole document replaced, every range lost and looked for.
        editor.commands.setContent(PLAN.replace('Test with', 'Test it with'), { contentType: 'markdown' })
        expect(quoteOf(editor, 'open')).toBe('Test it with a large report')
        expect(quoteOf(editor, 'done')).toBeUndefined()
        editor.commands.setContent(PLAN.replace('Test with a large report', 'Ship it.'), { contentType: 'markdown' })
        expect(quoteOf(editor, 'open')).toBeUndefined()
    })

    it('finds a reworded passage nearest where it was, of copies alike', () => {
        const filler = 'x'.repeat(40)
        const copies = `${filler}\n\nRetry the upload twice.\n\n`.repeat(3) + filler
        const editor = open(copies)
        const second = posOf(editor, 'Retry', 2)
        const anchor = anchorFor(editor.state, second, second + 'Retry the upload twice'.length)
        if (!anchor) {
            throw new Error('no anchor')
        }
        // Commented on there, as the editor adds a thread: synced alone, its words would find the first copy.
        const range = { from: second, to: second + 'Retry the upload twice'.length }
        editor.view.dispatch(withHighlight(editor.state.tr, { kind: 'add', id: 'a', range }))
        sync(editor, [{ id: 'a', anchor, resolved: false }])
        expect(highlightsKey.getState(editor.state)?.ranges.get('a')?.from).toBe(second)
        editor.commands.setContent(copies.replaceAll('twice', 'two times'), { contentType: 'markdown' })
        expect(highlightsKey.getState(editor.state)?.ranges.get('a')?.from).toBe(posOf(editor, 'Retry', 2))
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

    it('closes the open thread when the cursor leaves its passage, and keeps it while the cursor is in it', () => {
        const editor = open(PLAN)
        sync(editor, [placed('a', 'the rows')])
        const range = highlightsKey.getState(editor.state)?.ranges.get('a')
        if (!range) {
            throw new Error('no range')
        }
        editor.view.dispatch(withHighlight(editor.state.tr, { kind: 'activate', id: 'a' }))
        editor.commands.setTextSelection(range.to)
        expect(highlightsKey.getState(editor.state)?.active).toBe('a')
        editor.commands.setTextSelection(range.from + 3)
        editor.commands.insertContent('raw ')
        expect(highlightsKey.getState(editor.state)?.active).toBe('a')
        editor.commands.setTextSelection(1)
        expect(highlightsKey.getState(editor.state)?.active).toBeUndefined()
    })

    it('opens the thread whose passage the cursor moves into, the innermost, never a resolved one', () => {
        const editor = open(PLAN)
        sync(editor, [placed('a', 'Stream the rows'), placed('b', 'the rows'), placed('c', 'a large report', true)])
        editor.commands.setTextSelection(posOf(editor, 'Stream') + 1)
        expect(highlightsKey.getState(editor.state)?.active).toBe('a')
        editor.commands.setTextSelection(posOf(editor, 'rows') + 1)
        expect(highlightsKey.getState(editor.state)?.active).toBe('b')
        editor.commands.setTextSelection(posOf(editor, 'large') + 1)
        expect(highlightsKey.getState(editor.state)?.active).toBeUndefined()
    })

    it('closes the open thread on Escape, and leaves Escape alone with none open', () => {
        const editor = open(PLAN)
        sync(editor, [placed('a', 'the rows')])
        expect(press(editor, 'Escape')).toBe(false)
        editor.view.dispatch(withHighlight(editor.state.tr, { kind: 'activate', id: 'a' }))
        expect(press(editor, 'Escape')).toBe(true)
        expect(highlightsKey.getState(editor.state)?.active).toBeUndefined()
    })

    it('closes the open thread when it is resolved', () => {
        const editor = open(PLAN)
        sync(editor, [placed('a', 'the rows')])
        editor.view.dispatch(withHighlight(editor.state.tr, { kind: 'activate', id: 'a' }))
        sync(editor, [placed('a', 'the rows', true)])
        expect(highlightsKey.getState(editor.state)?.active).toBeUndefined()
    })

    it('draws the passage being commented on as the open one, in place of the thread that was', () => {
        const editor = open(PLAN)
        sync(editor, [placed('a', 'the rows')])
        editor.view.dispatch(withHighlight(editor.state.tr, { kind: 'activate', id: 'a' }))
        editor.view.dispatch(withHighlight(editor.state.tr, { kind: 'draft', range: { from: 1, to: 3 } }))
        expect(highlightsKey.getState(editor.state)?.active).toBeUndefined()
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

    it("opens the clicked passage's thread, the innermost of two that overlap, never a resolved one", async () => {
        const editor = open(PLAN)
        sync(editor, [placed('outer', 'Stream the rows'), placed('inner', 'the rows'), placed('done', 'large', true)])
        const opened: string[] = []
        editor.on('planThreadActivate', ({ id }) => {
            opened.push(id)
        })
        const click = (word: string) =>
            editor.view.someProp('handleClick', (handle) =>
                handle(editor.view, posOf(editor, word), new MouseEvent('click')),
            )

        // No handler takes the click, so ProseMirror still places the cursor.
        expect(click('the')).toBeUndefined()
        click('Stream')
        click('large')
        click('Plan')
        await new Promise((resolve) => {
            setTimeout(resolve, 0)
        })
        expect(opened).toEqual(['inner', 'outer'])
    })
})
