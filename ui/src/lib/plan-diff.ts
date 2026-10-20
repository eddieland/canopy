// What changed in a plan since the one it replaces (docs/design/PLANNING.md §25, Commenting on a plan): the words the
// new plan added and those it removed, drawn over the plan in its editor while the operator asks to see them. A new
// plan answers comments by rewriting passages, and the operator reads what changed rather than the whole plan again.
// The words are compared as the editor reads them (`docText`), so a change of formatting alone is no change, and both
// plans are read by the same parser. Added words are drawn as `ins`, removed ones as a `del` where they were; a block
// the new plan added whole (a paragraph, a heading, a table's cell) is marked as one, `plan-block-add` or
// `plan-cell-add`, rather than as a run of `ins`, which its marks and code spans would break into many. A passage
// rewritten around a few words it kept is the old passage removed and the new one added, not shreds of both. All are
// decorations, so the plan's Markdown holds nothing of them, and the removed words are the old plan's, set as text.
import { Extension } from '@tiptap/core'
import type { Editor } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import type { EditorState, Transaction } from '@tiptap/pm/state'
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { diffArrays } from 'diff'
import type { ArrayChange } from 'diff'

import { docText, rangeOf } from '@/lib/plan-schema'

/** A run of words: kept, added by the new plan, or removed from the old one. */
export interface Change {
    /** Whether the run is in both plans, only the new one, or only the old one. */
    kind: 'same' | 'add' | 'del'
    /** Its text. */
    text: string
    /** Where it is in the new plan's text: where it starts, or for a removed run, where it was. */
    at: number
}

/** The diff's state: the old plan's text, while changes are shown, what the editor draws, and where each change is. */
export interface Changes {
    /** The old plan's text as the editor reads it, while changes are shown. */
    base: string | undefined
    /** The added words and the removed ones, as the editor draws them. */
    decorations: DecorationSet
    /** Where each change starts in the plan, in its order, a removal and the words that replaced it one change. */
    starts: number[]
}

// A letter or a digit: what makes text a word rather than spaces or punctuation.
const WORD = /[\p{L}\p{N}]/u

/** How many words may differ before the plans are shown as all changed: past it, the comparison costs too much. */
export const MAX_EDITS = 2000

/** What a transaction tells the plugin, as its meta under `changesKey`: the old plan's text, or none to stop. */
export interface ChangesAction {
    /** The old plan's text as the editor reads it (`textOf`), or undefined to stop showing changes. */
    base: string | undefined
}

/** The plugin's key: a transaction's meta under it is a `ChangesAction`. */
export const changesKey = new PluginKey<Changes>('planChanges')

/** Draws what changed since the old plan its state holds; it holds none, and draws nothing, until told one. */
export const PlanChanges = Extension.create({
    name: 'planChanges',
    addProseMirrorPlugins() {
        return [
            new Plugin<Changes>({
                key: changesKey,
                state: {
                    init: () => ({ base: undefined, decorations: DecorationSet.empty, starts: [] }),
                    apply: (tr, prev, _, state) => next(tr, prev, state),
                },
                props: {
                    decorations: (state) => changesKey.getState(state)?.decorations,
                },
            }),
        ]
    },
})

/**
 * The runs of words that make `after` from `before`, in `after`'s order, a removed run before the run that replaced
 * it. Each word is compared whole, without the spaces after it, and carries them in its run. Past `cap` edits, the
 * part that differs is one removed run and one added.
 */
export function diffWords(before: string, after: string, cap = MAX_EDITS): Change[] {
    const a = tokens(before)
    const b = tokens(after)
    // Each word is compared without the spaces after it, so a word that ends a sentence in one plan and goes on in the
    // other (`hour.`, `hour the`) is the same word; what is kept is the new plan's, spaces and all.
    const keysA = a.map((token) => key(token))
    const keysB = b.map((token) => key(token))
    let start = 0
    while (start < a.length && start < b.length && keysA[start] === keysB[start]) {
        start += 1
    }
    let endA = a.length
    let endB = b.length
    while (endA > start && endB > start && keysA[endA - 1] === keysB[endB - 1]) {
        endA -= 1
        endB -= 1
    }
    const removed = a.slice(start, endA)
    const added = b.slice(start, endB)
    const middle = diffArrays(removed, added, { maxEditLength: cap, comparator: (x, y) => key(x) === key(y) }) ?? [
        part(removed, 'del'),
        part(added, 'add'),
    ]
    return runs(readable([part(b.slice(0, start), 'same'), ...middle, part(b.slice(endB), 'same')], a))
}

/** The plain text of a plan's Markdown as the editor reads it, to compare with the plan open in `editor`. */
export function textOf(editor: Editor, markdown: string): string {
    const json = editor.markdown?.parse(markdown)
    return json === undefined ? markdown : docText(editor.schema.nodeFromJSON(json)).text
}

function next(tr: Transaction, prev: Changes, state: EditorState): Changes {
    const action = tr.getMeta(changesKey) as ChangesAction | undefined
    if (action === undefined && !tr.docChanged) {
        return prev
    }
    const base = action === undefined ? prev.base : action.base
    return base === undefined ? { base, decorations: DecorationSet.empty, starts: [] } : { base, ...draw(state, base) }
}

function draw(state: EditorState, base: string): Pick<Changes, 'decorations' | 'starts'> {
    const { text, positions } = docText(state.doc)
    const decorations: Decoration[] = []
    const starts = new Set<number>()
    for (const change of diffWords(base, text)) {
        if (change.kind === 'same' || change.text.trim() === '') {
            continue
        }
        if (change.kind === 'add') {
            const range = rangeOf(positions, change.at, change.at + change.text.trimEnd().length)
            if (range !== undefined) {
                starts.add(range.from)
                decorations.push(...addedMarks(state.doc, range.from, range.to))
            }
        } else {
            const removed = change.text.replaceAll(/\s+/gu, ' ').trim()
            const where = at(positions, change.at)
            decorations.push(Decoration.widget(where, () => struck(removed), { side: -1 }))
            starts.add(where)
        }
    }
    return {
        decorations: DecorationSet.create(state.doc, decorations),
        starts: [...starts].toSorted((a, b) => a - b),
    }
}

// The decorations for words added from `from` to `to`, which may span blocks: each block they cover whole is marked
// as one, and the words in the rest as `ins`.
function addedMarks(doc: ProseMirrorNode, from: number, to: number): Decoration[] {
    const out: Decoration[] = []
    doc.nodesBetween(from, to, (node, pos) => {
        if (!node.isTextblock) {
            return true
        }
        const start = pos + 1
        const end = pos + node.nodeSize - 1
        const lo = Math.max(from, start)
        const hi = Math.min(to, end)
        if (lo < hi) {
            // Whole when what it leaves out of the block is no word: spaces, or a stop the old plan's words share.
            const whole = !WORD.test(doc.textBetween(start, lo)) && !WORD.test(doc.textBetween(hi, end))
            out.push(
                whole ? wholeBlock(doc, pos, node) : Decoration.inline(lo, hi, { nodeName: 'ins', class: 'plan-ins' }),
            )
        }
        return false
    })
    return out
}

// A block added whole, marked as one; the only block in a table's cell marks the cell, so a new table's cells tint as
// the table's grid rather than as strips inside it.
function wholeBlock(doc: ProseMirrorNode, pos: number, node: ProseMirrorNode): Decoration {
    const cell = doc.resolve(pos)
    const role: unknown = cell.parent.type.spec.tableRole
    if ((role === 'cell' || role === 'header_cell') && cell.parent.childCount === 1) {
        const from = cell.before()
        return Decoration.node(from, from + cell.parent.nodeSize, { class: 'plan-cell-add' })
    }
    return Decoration.node(pos, pos + node.nodeSize, { class: 'plan-block-add' })
}

// Where the text's offset `offset` falls in the document: just after the character before it, so words removed at the
// end of a paragraph show there, or at the next character when none comes before it in its block.
function at(positions: readonly number[], offset: number): number {
    const before = positions[offset - 1] ?? -1
    if (before >= 0) {
        return before + 1
    }
    for (let i = offset; i < positions.length; i += 1) {
        const pos = positions[i] ?? -1
        if (pos >= 0) {
            return pos
        }
    }
    const last = positions.findLast((pos) => pos >= 0)
    return last === undefined ? 0 : last + 1
}

// The words the new plan removed, as text: they are the old plan's, model-written, so never markup.
function struck(text: string): HTMLElement {
    const element = document.createElement('del')
    element.className = 'plan-del'
    element.contentEditable = 'false'
    element.textContent = text
    return element
}

// A word as it is compared: without the spaces after it, but a line break is still its own.
function key(token: string): string {
    return token.replace(/[^\S\n]+$/u, '')
}

// A text's words and each other character, in order, each with the spaces after it, so words replaced side by side
// read as one change rather than several split by the spaces they share; each line break, between the plan's
// blocks, is its own, so the blocks hold the comparison in place.
function tokens(text: string): string[] {
    return text.match(/[\p{L}\p{N}_]+[^\S\n]*|[^\s\p{L}\p{N}_][^\S\n]*|\n|[^\S\n]+/gu) ?? []
}

// Words as one part of a diff, as `diffArrays` writes its parts.
function part(words: string[], kind: Change['kind']): ArrayChange<string> {
    return { value: words, added: kind === 'add', removed: kind === 'del', count: words.length }
}

// The parts with each short run of kept words between two changes folded into them, as diff-match-patch's semantic
// cleanup does: a passage rewritten around a few words it kept (`the`, `to`) reads as the old passage and the new one,
// rather than as shreds of each. A kept run is short when it is no longer than the larger side of the change before it
// and of the change after it. A run that holds a line break is never folded, so a change stays in its blocks. A kept
// part holds the new text's words, so a folded run is removed as the old text's, from `before`, which may space it
// otherwise.
function readable(parts: readonly ArrayChange<string>[], before: readonly string[]): ArrayChange<string>[] {
    const out: Piece[] = []
    let old = 0
    for (const { value, added, removed } of parts) {
        const last = out.at(-1)
        if (!added) {
            old += value.length
        }
        if (value.length === 0) {
            continue
        }
        if (!added && !removed) {
            out.push({ kind: 'same', words: [...value], old: before.slice(old - value.length, old) })
            continue
        }
        if (last?.kind === 'change') {
            last[removed ? 'del' : 'add'].push(...value)
        } else {
            out.push({ kind: 'change', del: removed ? [...value] : [], add: added ? [...value] : [] })
        }
        fold(out)
    }
    return out.flatMap((piece) =>
        piece.kind === 'same' ? [part(piece.words, 'same')] : [part(piece.del, 'del'), part(piece.add, 'add')],
    )
}

// A run of kept words, as the new text and the old one space them, or a change: the words it removed and those it
// added in their place.
type Piece = { kind: 'same'; words: string[]; old: string[] } | { kind: 'change'; del: string[]; add: string[] }

// Folds the kept run before the last change into the changes on each side while it is short, and goes on with the
// run before, since the change it makes is larger.
function fold(out: Piece[]): void {
    for (;;) {
        const [before, kept, after] = out.slice(-3)
        if (before?.kind !== 'change' || kept?.kind !== 'same' || after?.kind !== 'change') {
            return
        }
        const length = kept.words.join('').length
        if (kept.words.includes('\n') || length > size(before) || length > size(after)) {
            return
        }
        out.splice(-3, 3, {
            kind: 'change',
            del: [...before.del, ...kept.old, ...after.del],
            add: [...before.add, ...kept.words, ...after.add],
        })
    }
}

// How long a change is: its larger side, in characters.
function size(change: { del: string[]; add: string[] }): number {
    return Math.max(change.del.join('').length, change.add.join('').length)
}

// The parts as runs of text, each with where it is in the new text. A kept part is the new plan's words, as
// `diffArrays` keeps them; an empty part is left out.
function runs(parts: readonly ArrayChange<string>[]): Change[] {
    const out: Change[] = []
    let offset = 0
    for (const { value, added, removed } of parts) {
        const kind: Change['kind'] = added ? 'add' : removed ? 'del' : 'same'
        const text = value.join('')
        if (text === '') {
            continue
        }
        const last = out.at(-1)
        if (last?.kind === kind) {
            last.text += text
        } else {
            out.push({ kind, text, at: offset })
        }
        if (kind !== 'del') {
            offset += text.length
        }
    }
    return out
}
