// A plan's table, as Tiptap's table draws one, with room beside it for its actions (src/lib/block-slots.ts,
// src/components/block-actions.tsx): its rows copied as Markdown or for a spreadsheet, or saved as CSV. The view is
// Tiptap's own, in a block of its own that holds the room for the actions too, so the table still scrolls in its
// wrapper while the actions stay in the block's corner.
import { mergeAttributes } from '@tiptap/core'
import type { Editor } from '@tiptap/core'
import { Table, TableView } from '@tiptap/extension-table'
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'
import type { EditorView } from '@tiptap/pm/view'

import { blockSlots, newSlotId } from '@/lib/block-slots'
import type { BlockSlots } from '@/lib/block-slots'

/** A plan's table, drawn with room for its actions. */
export const PlanTable = Table.extend({
    addNodeView() {
        const { editor, options } = this
        return ({ node, view, HTMLAttributes }) =>
            new PlanTableView(
                node,
                options.cellMinWidth,
                view,
                mergeAttributes(options.HTMLAttributes, HTMLAttributes),
                {
                    slots: blockSlots(editor),
                    markdown: (table) => tableMarkdown(editor, table),
                },
            )
    },
})

/** A table's view: Tiptap's, in a block that holds the room for its actions beside it. */
export class PlanTableView extends TableView {
    private readonly actions: HTMLElement
    private readonly slots: BlockSlots
    private readonly markdown: (table: ProseMirrorNode) => string
    private readonly id = newSlotId()

    constructor(
        node: ProseMirrorNode,
        cellMinWidth: number,
        view: EditorView,
        attributes: Record<string, unknown>,
        what: { slots: BlockSlots; markdown: (table: ProseMirrorNode) => string },
    ) {
        super(node, cellMinWidth, view, attributes)
        this.slots = what.slots
        this.markdown = what.markdown
        const wrapper = this.dom
        this.dom = document.createElement('div')
        // A block whose actions show while it is hovered (`block-actions`, src/index.css).
        this.dom.className = 'plan-table group/block'
        this.actions = document.createElement('div')
        this.actions.className = 'block-actions'
        this.actions.contentEditable = 'false'
        this.dom.append(wrapper, this.actions)
        this.publish(node)
    }

    override update(node: ProseMirrorNode): boolean {
        const kept = super.update(node)
        if (kept) {
            this.publish(node)
        }
        return kept
    }

    // Its actions are not the document: what is done to them is their own. What changes in them is not an edit
    // either, and needs no `ignoreMutation` of its own: Tiptap's ignores every change inside `this.dom`, which holds
    // them, that is not inside its cells.
    stopEvent(event: Event): boolean {
        return event.target instanceof globalThis.Node && this.actions.contains(event.target)
    }

    destroy(): void {
        this.slots.remove(this.id)
    }

    // Says what the table's actions act on now: its rows, and its Markdown.
    private publish(table: ProseMirrorNode): void {
        this.slots.put({
            id: this.id,
            kind: 'table',
            slot: this.actions,
            rows: tableRows(table),
            markdown: this.markdown(table),
        })
    }
}

/**
 * `table`'s rows, its header row first, each cell its words on one line: code without its backticks, a link its
 * text.
 */
export function tableRows(table: ProseMirrorNode): string[][] {
    const rows: string[][] = []
    table.forEach((row) => {
        const cells: string[] = []
        row.forEach((cell) => {
            const words = cell.textBetween(0, cell.content.size, ' ', (leaf) => leafText(leaf))
            cells.push(words.replaceAll(/\s+/gu, ' ').trim())
        })
        rows.push(cells)
    })
    return rows
}

// What an inline leaf of a cell reads as: the characters a verbatim one keeps, or a space for a break.
function leafText(leaf: ProseMirrorNode): string {
    const raw: unknown = leaf.attrs['raw']
    if (leaf.type.name === 'softBreak' || leaf.type.name === 'hardBreak') {
        return ' '
    }
    return typeof raw === 'string' ? raw : ''
}

// `table` as the plan's Markdown writes it, without the blank lines around it.
function tableMarkdown(editor: Editor, table: ProseMirrorNode): string {
    return (editor.markdown?.serialize({ type: 'doc', content: [table.toJSON()] }) ?? '').trim()
}
