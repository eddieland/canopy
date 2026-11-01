// What changed in a plan since the one it replaces (docs/design/PLANNING.md §25, Commenting on a plan): the words the
// new plan added and those it removed, drawn over the plan in its editor while the operator asks to see them. A new
// plan answers comments by rewriting passages, and the operator reads what changed rather than the whole plan again.
// The words are compared as the editor reads them (`docText`), so a change of formatting alone is no change, and both
// plans are read by the same parser. Added words are drawn as `ins`, removed ones as a `del` where they were; a block
// the new plan added whole (a paragraph, a heading, a table's cell) is marked as one, `plan-block-add` or
// `plan-cell-add`, rather than as a run of `ins`, which its marks and code spans would break into many. A passage
// rewritten around a few words it kept is the old passage removed and the new one added, not shreds of both. The
// plans are first lined up section by section, a section being a heading and what follows it to the next, matched by
// its headings or, failing that, by its words; the words are compared within each pair. A section that moved is
// marked `moved` where it is now, and one the new plan dropped is one folded `Section removed` where it was, rather
// than a wall of struck words. All are decorations, so the plan's Markdown holds nothing of them, and the removed
// words are the old plan's, set as text.
import { Extension } from '@tiptap/core'
import type { Editor } from '@tiptap/core'
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'
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

/** A plan as the diff compares it: its text as the editor reads it, cut into sections at its headings. */
export interface Outline {
    /** The plan's text, as `docText` reads it. */
    text: string
    /** Its sections in order, the first the text before any heading, which may be empty. */
    sections: Section[]
}

/** A heading and what follows it up to the next heading, as a slice of its outline's text. */
export interface Section {
    /** Its heading's words and those of the headings it sits under, which name it among the plan's sections. */
    key: string
    /** Its heading's words, or none for the text before the first heading. */
    heading: string
    /** Its heading's level, or 0 for the text before the first heading. */
    level: number
    /** Where it starts in the text: where its heading's words start. */
    start: number
    /** Where it ends: where the next starts, or the text's end. */
    end: number
}

/** What changed between two plans: the runs of words, and the sections moved and removed whole. */
export interface PlanDiff {
    /** The runs of words in the new plan's order, each where it is in its text, as `diffWords` gives them. */
    changes: Change[]
    /** Where each section the new plan moved starts in its text. */
    moved: number[]
    /** The sections the new plan dropped, in the old plan's order. */
    removed: Removed[]
}

/** A section the new plan dropped. */
export interface Removed {
    /** Where it was, in the new plan's text: where the section that followed it there starts, or the text's end. */
    at: number
    /** Its heading's words. */
    heading: string
    /** What followed its heading. */
    body: string
}

/** The diff's state: the old plan, while changes are shown, what the editor draws, and where each change is. */
export interface Changes {
    /** The old plan as the editor reads it, while changes are shown. */
    base: Outline | undefined
    /** The added words and the removed ones, as the editor draws them. */
    decorations: DecorationSet
    /** Where each change starts in the plan, in its order, a removal and the words that replaced it one change. */
    starts: number[]
}

// A letter or a digit: what makes text a word rather than spaces or punctuation.
const WORD = /[\p{L}\p{N}]/u

/** How many words may differ before the plans are shown as all changed: past it, the comparison costs too much. */
export const MAX_EDITS = 2000

/** What a transaction tells the plugin, as its meta under `changesKey`: the old plan, or none to stop. */
export interface ChangesAction {
    /** The old plan as the editor reads it (`outlineOf`), or undefined to stop showing changes. */
    base: Outline | undefined
}

/** Two sections that share no heading are the same one moved or renamed when this much of their words is shared. */
export const SAME_SECTION = 0.5

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
 * What changed from the plan `before` to the plan `after`: their sections are lined up first, by their headings, then
 * those left by their words, and the words compared within each pair. A pair out of the old plan's order is a section
 * moved, the fewest that put the rest in order; a section of the new plan with no pair is added whole, and one of the
 * old plan's is removed whole, where the section after it in the old plan now is.
 */
export function diffPlans(before: Outline, after: Outline, cap = MAX_EDITS): PlanDiff {
    const pairs = pair(before, after)
    const kept = inOrder(pairs)
    const changes: Change[] = []
    const moved: number[] = []
    after.sections.forEach((section, index) => {
        const text = textOf(after, section)
        const old = pairs.get(index)
        if (old === undefined) {
            if (text !== '') {
                changes.push({ kind: 'add', text, at: section.start })
            }
            return
        }
        const was = before.sections[old]
        const words = diffWords(was === undefined ? '' : textOf(before, was), text, cap)
        for (const change of words) {
            change.at += section.start
            changes.push(change)
        }
        if (!kept.has(index)) {
            moved.push(section.start)
        }
    })
    // Where each old section went, for the ones kept in order: a removed one is drawn before the next of them.
    const where = new Map([...pairs].filter(([index]) => kept.has(index)).map(([index, old]) => [old, index]))
    const paired = new Set(pairs.values())
    const removed: Removed[] = []
    before.sections.forEach((section, old) => {
        if (paired.has(old)) {
            return
        }
        let later = old + 1
        while (later < before.sections.length && !where.has(later)) {
            later += 1
        }
        const index = where.get(later)
        const text = textOf(before, section)
        const line = text.indexOf('\n')
        removed.push({
            at: index === undefined ? after.text.length : (after.sections[index]?.start ?? after.text.length),
            heading: section.heading,
            body: line === -1 ? '' : text.slice(line + 1).trim(),
        })
    })
    return { changes, moved, removed }
}

// A section's text, without the line break that ends it unless it is the plan's last.
function textOf(outline: Outline, section: Section): string {
    return outline.text.slice(section.start, section.end).replace(/\n$/u, '')
}

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

/** A plan's Markdown as the editor reads it, cut into its sections, to compare with the plan open in `editor`. */
export function outlineOf(editor: Editor, markdown: string): Outline {
    const json = editor.markdown?.parse(markdown)
    if (json === undefined) {
        return { text: markdown, sections: [{ key: '', heading: '', level: 0, start: 0, end: markdown.length }] }
    }
    return read(editor.schema.nodeFromJSON(json)).outline
}

function next(tr: Transaction, prev: Changes, state: EditorState): Changes {
    const action = tr.getMeta(changesKey) as ChangesAction | undefined
    if (action === undefined && !tr.docChanged) {
        return prev
    }
    const base = action === undefined ? prev.base : action.base
    return base === undefined ? { base, decorations: DecorationSet.empty, starts: [] } : { base, ...draw(state, base) }
}

// A document's outline, and where each character of its text is in the document, as `docText` says.
function read(doc: ProseMirrorNode): { outline: Outline; positions: number[] } {
    const { text, positions } = docText(doc)
    const sections: Section[] = [{ key: '', heading: '', level: 0, start: 0, end: text.length }]
    // The headings the next one sits under, by level.
    const path: { level: number; words: string }[] = []
    // Where the text reaches the node being read: the headings come in the text's order, so it only moves on.
    let start = 0
    doc.descendants((node, pos) => {
        if (node.type.name !== 'heading') {
            return !node.isTextblock
        }
        while (start < positions.length && (positions[start] ?? -1) < pos) {
            start += 1
        }
        const words = node.textContent.replaceAll(/\s+/gu, ' ').trim()
        // A heading with no words names no section: its text is the one before's.
        if (words === '' || start >= text.length) {
            return false
        }
        const level = Number(node.attrs['level'])
        while ((path.at(-1)?.level ?? 0) >= level) {
            path.pop()
        }
        path.push({ level, words })
        const last = sections.at(-1)
        if (last !== undefined) {
            last.end = start
        }
        sections.push({
            key: path.map((heading) => heading.words.toLowerCase()).join('\n'),
            heading: words,
            level,
            start,
            end: text.length,
        })
        return false
    })
    return { outline: { text, sections }, positions }
}

// Which old section each new one is, by index: first those under the same headings, then those of the same heading
// under others, each in order, then of those left the pairs whose words are most alike, while they share at least
// `SAME_SECTION` of them. Those still left are paired in order when they are of a level and lie between the same
// two pairs in order, as a heading rewritten with its words would. The text before the first heading is always the
// old one's.
function pair(before: Outline, after: Outline): Map<number, number> {
    const pairs = new Map<number, number>([[0, 0]])
    const paired = new Set([0])
    for (const name of [(section: Section) => section.key, (section: Section) => section.heading.toLowerCase()]) {
        const named = new Map<string, number[]>()
        before.sections.forEach((section, old) => {
            if (!paired.has(old)) {
                named.set(name(section), [...(named.get(name(section)) ?? []), old])
            }
        })
        after.sections.forEach((section, index) => {
            const old = pairs.has(index) ? undefined : named.get(name(section))?.shift()
            if (old !== undefined) {
                pairs.set(index, old)
                paired.add(old)
            }
        })
    }
    const olds = before.sections.flatMap((section, old) =>
        paired.has(old) ? [] : [{ old, words: wordsOf(before, section) }],
    )
    const candidates: { index: number; old: number; score: number }[] = []
    after.sections.forEach((section, index) => {
        if (pairs.has(index)) {
            return
        }
        const words = wordsOf(after, section)
        for (const { old, words: was } of olds) {
            const score = alike(words, was)
            if (score >= SAME_SECTION) {
                candidates.push({ index, old, score })
            }
        }
    })
    for (const { index, old } of candidates.toSorted((x, y) => y.score - x.score)) {
        if (!pairs.has(index) && !paired.has(old)) {
            pairs.set(index, old)
            paired.add(old)
        }
    }
    const kept = [...inOrder(pairs)].toSorted((x, y) => x - y)
    kept.forEach((index, i) => {
        const following = kept[i + 1]
        const gapOlds = between(
            pairs.get(index) ?? 0,
            following === undefined ? before.sections.length : (pairs.get(following) ?? 0),
        )
        const left = gapOlds.filter((old) => !paired.has(old))
        for (const gap of between(index, following ?? after.sections.length)) {
            const old = left.find((was) => before.sections[was]?.level === after.sections[gap]?.level)
            if (!pairs.has(gap) && old !== undefined) {
                pairs.set(gap, old)
                paired.add(old)
                left.splice(0, left.indexOf(old) + 1)
            }
        }
    })
    return pairs
}

// The numbers after `from` and before `to`.
function between(from: number, to: number): number[] {
    return Array.from({ length: Math.max(0, to - from - 1) }, (_, i) => from + 1 + i)
}

// A section's words, lowercased, each once.
function wordsOf(outline: Outline, section: Section): Set<string> {
    return new Set(
        outline.text
            .slice(section.start, section.end)
            .toLowerCase()
            .match(/[\p{L}\p{N}_]+/gu),
    )
}

// How much of their words two sets share: those in both, of those in either.
function alike(a: ReadonlySet<string>, b: ReadonlySet<string>): number {
    const both = [...a].filter((word) => b.has(word)).length
    const either = a.size + b.size - both
    return either === 0 ? 1 : both / either
}

// The new sections whose pairs are in the old plan's order: the most of them that are, so the fewest are moved.
function inOrder(pairs: ReadonlyMap<number, number>): Set<number> {
    const indexes = [...pairs.keys()].toSorted((x, y) => x - y)
    const olds = indexes.map((index) => pairs.get(index) ?? 0)
    // For each, how long the longest run in order that ends with it is, and the one before it in that run.
    const lengths: number[] = []
    const previous: number[] = []
    olds.forEach((old, i) => {
        let best = 1
        let from = -1
        for (let j = 0; j < i; j += 1) {
            const length = (lengths[j] ?? 0) + 1
            if ((olds[j] ?? 0) < old && length > best) {
                best = length
                from = j
            }
        }
        lengths.push(best)
        previous.push(from)
    })
    const kept = new Set<number>()
    for (let i = lengths.indexOf(Math.max(...lengths)); i >= 0; i = previous[i] ?? -1) {
        kept.add(indexes[i] ?? 0)
    }
    return kept
}

function draw(state: EditorState, base: Outline): Pick<Changes, 'decorations' | 'starts'> {
    const { outline, positions } = read(state.doc)
    const { text } = outline
    const diff = diffPlans(base, outline)
    const decorations: Decoration[] = []
    const starts = new Set<number>()
    for (const offset of diff.moved) {
        const heading = state.doc.resolve(at(positions, offset))
        decorations.push(Decoration.widget(heading.end(), () => badge('moved'), { side: 1 }))
        starts.add(heading.start())
    }
    for (const section of diff.removed) {
        const where =
            section.at >= text.length ? state.doc.content.size : blockStart(state.doc, at(positions, section.at))
        decorations.push(
            Decoration.widget(where, () => folded(section), { side: -1, stopEvent: () => true, ignoreSelection: true }),
        )
        starts.add(where)
    }
    for (const change of diff.changes) {
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

// Where the block holding `pos` starts, before its opening: where a section removed before it is drawn.
function blockStart(doc: ProseMirrorNode, pos: number): number {
    const resolved = doc.resolve(pos)
    return resolved.depth === 0 ? pos : resolved.before(resolved.depth)
}

// What a moved section's heading carries at its end.
function badge(text: string): HTMLElement {
    const element = document.createElement('span')
    element.className = 'plan-moved'
    element.contentEditable = 'false'
    element.textContent = text
    return element
}

// A section the new plan removed, folded to its heading, its words struck under it when opened: they are the old
// plan's, model-written, so set as text.
function folded(section: Removed): HTMLElement {
    const element = document.createElement('details')
    element.className = 'plan-section-del'
    element.contentEditable = 'false'
    const summary = document.createElement('summary')
    summary.textContent = `Section removed: ${section.heading}`
    element.append(summary)
    if (section.body !== '') {
        const body = document.createElement('del')
        body.className = 'plan-del'
        body.textContent = section.body
        element.append(body)
    }
    return element
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
