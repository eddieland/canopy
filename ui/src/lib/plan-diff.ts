// What changed in a plan since the one it replaces (docs/design/PLANNING.md §25, Commenting on a plan): the words the
// new plan added and those it removed, drawn over the plan in its editor while the operator asks to see them. A new
// plan answers comments by rewriting passages, and the operator reads what changed rather than the whole plan again.
// The words are compared as the editor reads them (`docText`), so a change of formatting alone is no change, and both
// plans are read by the same parser. Added words are drawn as `ins`, removed ones as a `del` where they were; both are
// decorations, so the plan's Markdown holds nothing of them, and the removed words are the old plan's, set as text.
import { Extension } from '@tiptap/core'
import type { Editor } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import type { EditorState, Transaction } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

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

/** The diff's state: the old plan's text, while changes are shown, and what the editor draws. */
interface Changes {
    base: string | undefined
    decorations: DecorationSet
}

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
                    init: () => ({ base: undefined, decorations: DecorationSet.empty }),
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
 * it. Each word is compared whole, with the spaces after it. Past `cap` edits, the part that differs is one removed
 * run and one added.
 */
export function diffWords(before: string, after: string, cap = MAX_EDITS): Change[] {
    const a = tokens(before)
    const b = tokens(after)
    let start = 0
    while (start < a.length && start < b.length && a[start] === b[start]) {
        start += 1
    }
    let endA = a.length
    let endB = b.length
    while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
        endA -= 1
        endB -= 1
    }
    const ops = [
        ...a.slice(0, start).map(() => SAME),
        ...edits(a.slice(start, endA), b.slice(start, endB), cap),
        ...a.slice(endA).map(() => SAME),
    ]
    return runs(a, b, ops)
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
    return { base, decorations: base === undefined ? DecorationSet.empty : draw(state, base) }
}

function draw(state: EditorState, base: string): DecorationSet {
    const { text, positions } = docText(state.doc)
    const decorations: Decoration[] = []
    for (const change of diffWords(base, text)) {
        if (change.kind === 'same' || change.text.trim() === '') {
            continue
        }
        if (change.kind === 'add') {
            const range = rangeOf(positions, change.at, change.at + change.text.trimEnd().length)
            if (range !== undefined) {
                decorations.push(Decoration.inline(range.from, range.to, { nodeName: 'ins', class: 'plan-ins' }))
            }
        } else {
            const removed = change.text.replaceAll(/\s+/gu, ' ').trim()
            decorations.push(Decoration.widget(at(positions, change.at), () => struck(removed), { side: -1 }))
        }
    }
    return DecorationSet.create(state.doc, decorations)
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

type Op = 'same' | 'add' | 'del'
const SAME: Op = 'same'

// A text's words and each other character, in order, each with the spaces after it, so words replaced side by side
// read as one change rather than several split by the spaces they share; each line break, between the plan's
// blocks, is its own, so the blocks hold the comparison in place.
function tokens(text: string): string[] {
    return text.match(/[\p{L}\p{N}_]+[^\S\n]*|[^\s\p{L}\p{N}_][^\S\n]*|\n|[^\S\n]+/gu) ?? []
}

// The shortest edits that make `b` from `a`, one op per word of either, by Myers' algorithm: each step `d` keeps how
// far along `a` each diagonal reached, and the steps are walked back to read the edits. Each step's record keeps only
// the diagonals it can read, -d-1 to d+1, so the memory grows with the edits rather than the plan. Past `cap` steps,
// every word of `a` removed and every word of `b` added.
function edits(a: readonly string[], b: readonly string[], cap: number): Op[] {
    const n = a.length
    const m = b.length
    const steps = Math.min(n + m, cap)
    const reach = new Int32Array(2 * steps + 3)
    const zero = steps + 1
    reach[zero + 1] = 0
    const trace: Int32Array[] = []
    for (let d = 0; d <= steps; d += 1) {
        trace.push(reach.slice(zero - d - 1, zero + d + 2))
        for (let k = -d; k <= d; k += 2) {
            const down = k === -d || (k !== d && (reach[zero + k - 1] ?? 0) < (reach[zero + k + 1] ?? 0))
            let x = down ? (reach[zero + k + 1] ?? 0) : (reach[zero + k - 1] ?? 0) + 1
            let y = x - k
            while (x < n && y < m && a[x] === b[y]) {
                x += 1
                y += 1
            }
            reach[zero + k] = x
            if (x >= n && y >= m) {
                return walkBack(trace, n, m)
            }
        }
    }
    return [...a.map((): Op => 'del'), ...b.map((): Op => 'add')]
}

// The edits read back from Myers' steps, from the end of both texts to their start. Step `d`'s record holds diagonal
// `k` at `k + d + 1`.
function walkBack(trace: readonly Int32Array[], n: number, m: number): Op[] {
    const ops: Op[] = []
    let x = n
    let y = m
    for (let d = trace.length - 1; d >= 0; d -= 1) {
        const reach = trace[d] ?? new Int32Array()
        const zero = d + 1
        const k = x - y
        const down = k === -d || (k !== d && (reach[zero + k - 1] ?? 0) < (reach[zero + k + 1] ?? 0))
        const prevK = down ? k + 1 : k - 1
        const prevX = reach[zero + prevK] ?? 0
        const prevY = prevX - prevK
        while (x > prevX && y > prevY) {
            ops.push('same')
            x -= 1
            y -= 1
        }
        if (d > 0) {
            ops.push(x === prevX ? 'add' : 'del')
        }
        x = prevX
        y = prevY
    }
    return ops.toReversed()
}

// The ops as runs of text, each with where it is in `b`'s text.
function runs(a: readonly string[], b: readonly string[], ops: readonly Op[]): Change[] {
    const out: Change[] = []
    let i = 0
    let j = 0
    let offset = 0
    for (const op of ops) {
        const word = op === 'add' ? b[j] : a[i]
        const last = out.at(-1)
        if (last?.kind === op) {
            last.text += word ?? ''
        } else {
            out.push({ kind: op, text: word ?? '', at: offset })
        }
        if (op !== 'del') {
            offset += (b[j] ?? '').length
            j += 1
        }
        if (op !== 'add') {
            i += 1
        }
    }
    return out
}
