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
    return runs([part(b.slice(0, start), 'same'), ...middle, part(b.slice(endB), 'same')])
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
                decorations.push(Decoration.inline(range.from, range.to, { nodeName: 'ins', class: 'plan-ins' }))
                starts.add(range.from)
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
