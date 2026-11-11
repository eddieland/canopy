import { Editor } from '@tiptap/core'
import { afterEach, describe, expect, it } from 'vitest'

import { blockSlots } from '@/lib/block-slots'
import type { TableSlot } from '@/lib/block-slots'
import { planExtensions } from '@/lib/plan-schema'

const TABLE = [
    '| Repository | File | Why |',
    '| --- | :-- | --: |',
    '| web | `app/reports/export.py` | the new **route** |',
    '| api | `api/query.py` | 3 |',
].join('\n')

const editors: Editor[] = []

function open(markdown: string): { editor: Editor; root: HTMLElement } {
    const root = document.createElement('div')
    document.body.append(root)
    const editor = new Editor({
        element: root,
        extensions: planExtensions(),
        content: markdown,
        contentType: 'markdown',
    })
    editors.push(editor)
    return { editor, root }
}

// The document's tables' rooms for their actions.
function tables(editor: Editor): TableSlot[] {
    return blockSlots(editor)
        .snapshot()
        .filter((block): block is TableSlot => block.kind === 'table')
}

afterEach(() => {
    for (const editor of editors.splice(0)) {
        editor.destroy()
    }
    document.body.replaceChildren()
})

describe("a plan's table", () => {
    it('keeps room beside it for its actions, saying its rows and its Markdown', () => {
        const { editor, root } = open(`# Plan\n\n${TABLE}\n`)
        const [table] = tables(editor)
        expect(table?.rows).toEqual([
            ['Repository', 'File', 'Why'],
            ['web', 'app/reports/export.py', 'the new route'],
            ['api', 'api/query.py', '3'],
        ])
        expect(table?.markdown).toMatch(/^\| Repository +\| File +\| Why +\|\n/u)
        expect(table?.markdown).toContain('`app/reports/export.py`')
        expect(table?.slot.parentElement).toBe(root.querySelector('.plan-table'))
        expect(root.querySelector('.plan-table > .tableWrapper > table')).not.toBeNull()
    })

    it('says its rows again as they are edited', () => {
        const { editor } = open(`# Plan\n\n${TABLE}\n`)
        let cell = 0
        editor.state.doc.descendants((node, pos) => {
            if (cell === 0 && node.type.name === 'tableCell' && node.textContent === '3') {
                cell = pos + 2
            }
        })
        editor.commands.insertContentAt(cell, '4')
        expect(tables(editor)[0]?.rows[2]).toEqual(['api', 'api/query.py', '43'])
    })

    it('leaves the document when it does', () => {
        const { editor } = open(`# Plan\n\n${TABLE}\n`)
        editor.commands.setContent('# No table', { contentType: 'markdown' })
        expect(tables(editor)).toEqual([])
    })
})
