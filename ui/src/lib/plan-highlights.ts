// The comments' passages in a plan's editor, drawn as highlights over the text and kept on it while the operator edits.
// They are decorations, never part of the document, so the plan's Markdown holds nothing of them; the threads keep
// their places as anchors (`src/lib/plan-anchors.ts`), and this plugin turns those into ranges and back. A range moves
// with the edits around it; one whose text is deleted whole is lost, and found again if its passage comes back, as an
// undo brings it, or, for an open thread, if words much like it come back, nearest where it was. A resolved thread asks
// nothing more of its passage, so as Gerrit carries only unresolved comments to a new patchset, only its exact words
// find it. The open thread closes when the cursor leaves its passage, or on Escape, as a click elsewhere in a
// shared document closes a comment there. The plugin says what the operator does with the comments through the editor's
// own events, so the component listens in an effect rather than handing the plugin callbacks. The cursor in a passage,
// put there by a click or the keyboard, opens its thread, as the cursor in commented text does in a shared document.
import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import type { EditorState, Transaction } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

import { anchorAt, locate } from '@/lib/plan-anchors'
import type { Anchor } from '@/lib/plan-anchors'
import { docText, rangeOf, spanOf } from '@/lib/plan-schema'

declare module '@tiptap/core' {
    interface EditorEvents {
        /** The operator clicked a comment's passage: its thread's id. */
        planThreadActivate: { id: string }
        /** The operator asked to comment on the selection, by its shortcut. */
        planCommentRequest: Record<string, never>
    }
}

/** A comment's passage in the document, from `from` up to `to`. */
export interface Range {
    /** The document position where it starts. */
    from: number
    /** The document position where it ends. */
    to: number
}

/** What the plugin needs of a thread: its id, where it was, and whether it is resolved, which hides it. */
export interface Placed {
    /** The thread's id. */
    id: string
    /** Its passage, as last seen. */
    anchor: Anchor
    /** Whether it is resolved: its passage is still tracked, but not highlighted. */
    resolved: boolean
}

/** The highlights' state: the threads it was given, where each found one is, and which is active. */
export interface Highlights {
    /** The threads, as last synced. */
    threads: Placed[]
    /** Where each thread found in the document is. A thread missing here is lost. */
    ranges: ReadonlyMap<string, Range>
    /**
     * Where each thread lost to an edit was, as an index of the plan's text as it was then: where a passage reworded
     * is looked for first.
     */
    lost: ReadonlyMap<string, number>
    /** The thread whose passage is drawn as the one open, if any. */
    active: string | undefined
    /** The selection a comment is being written on, drawn as the active one is. */
    draft: Range | undefined
    /** What the editor draws. */
    decorations: DecorationSet
}

/** What a transaction can tell the plugin, as its meta under `highlightsKey`. */
export type HighlightAction =
    | { kind: 'sync'; threads: Placed[] }
    | { kind: 'add'; id: string; range: Range }
    | { kind: 'activate'; id: string | undefined }
    | { kind: 'draft'; range: Range | undefined }

/** The plugin's key: read its state with `highlightsKey.getState(state)`. */
export const highlightsKey = new PluginKey<Highlights>('planHighlights')

/**
 * The highlights, with Mod+Alt+M asking for a comment on the selection, as Google Docs has it, and Escape closing the
 * open thread.
 */
export const PlanHighlights = Extension.create({
    name: 'planHighlights',
    addProseMirrorPlugins() {
        const editor = this.editor
        return [
            new Plugin<Highlights>({
                key: highlightsKey,
                state: {
                    init: (_, state) => build(state, [], new Map(), new Map(), undefined, undefined),
                    apply: (tr, prev, _, state) => next(tr, prev, state),
                },
                props: {
                    decorations: (state) => highlightsKey.getState(state)?.decorations,
                    handleClick: (view, pos) => {
                        const id = threadAt(highlightsKey.getState(view.state), pos)
                        if (id !== undefined) {
                            // After the click has placed the cursor, so what the listener dispatches comes after it.
                            setTimeout(() => editor.emit('planThreadActivate', { id }), 0)
                        }
                        // The click still places the cursor.
                        return false
                    },
                },
            }),
        ]
    },
    addKeyboardShortcuts() {
        return {
            'Mod-Alt-m': () => {
                this.editor.emit('planCommentRequest', {})
                return true
            },
            Escape: () => {
                if (highlightsKey.getState(this.editor.state)?.active === undefined) {
                    return false
                }
                this.editor.view.dispatch(withHighlight(this.editor.state.tr, { kind: 'activate', id: undefined }))
                return true
            },
        }
    },
})

/** `action` as a transaction's meta, for `view.dispatch`. */
export function withHighlight(tr: Transaction, action: HighlightAction): Transaction {
    return tr.setMeta(highlightsKey, action)
}

/**
 * Each found thread's anchor and where its passage starts, from the document as it is now: what a caller saves after
 * an edit (`withAnchors`), and the order the threads list in (`inPlanOrder`).
 */
export function anchorsOf(state: EditorState): { anchors: Map<string, Anchor>; starts: Map<string, number> } {
    const anchors = new Map<string, Anchor>()
    const starts = new Map<string, number>()
    const highlights = highlightsKey.getState(state)
    if (highlights === undefined) {
        return { anchors, starts }
    }
    const { text, positions } = docText(state.doc)
    for (const [id, range] of highlights.ranges) {
        const span = spanOf(positions, range.from, range.to)
        const anchor = anchorAt(text, span.start, span.end)
        if (anchor !== undefined) {
            anchors.set(id, anchor)
            starts.set(id, range.from)
        }
    }
    return { anchors, starts }
}

/** The anchor for the document range `from` to `to`, or undefined when it holds no text to comment on. */
export function anchorFor(state: EditorState, from: number, to: number): Anchor | undefined {
    const { text, positions } = docText(state.doc)
    const span = spanOf(positions, from, to)
    return anchorAt(text, span.start, span.end)
}

function next(tr: Transaction, prev: Highlights, state: EditorState): Highlights {
    const action = tr.getMeta(highlightsKey) as HighlightAction | undefined
    const moved = tr.selectionSet && action === undefined
    if (!tr.docChanged && !moved && action === undefined) {
        return prev
    }
    if (!tr.docChanged && moved && threadAt(prev, tr.selection.head, true) === prev.active) {
        return prev
    }
    let { threads, active, draft } = prev
    let ranges = new Map<string, Range>()
    let lost = new Map(prev.lost)
    let before: ReturnType<typeof docText> | undefined
    for (const [id, range] of prev.ranges) {
        const mapped = mapRange(tr, range)
        if (mapped === undefined) {
            before ??= docText(tr.before)
            lost.set(id, spanOf(before.positions, range.from, range.to).start)
        } else {
            ranges.set(id, mapped)
        }
    }
    draft = draft === undefined ? undefined : mapRange(tr, draft)
    switch (action?.kind) {
        case 'sync': {
            threads = action.threads
            const ids = new Set(threads.map((thread) => thread.id))
            ranges = new Map([...ranges].filter(([id]) => ids.has(id)))
            lost = new Map([...lost].filter(([id]) => ids.has(id)))
            break
        }
        case 'add': {
            ranges.set(action.id, action.range)
            draft = undefined
            active = action.id
            break
        }
        case 'activate': {
            active = action.id
            break
        }
        case 'draft': {
            draft = action.range
            // The passage being commented on is the one drawn open now.
            if (draft !== undefined) {
                active = undefined
            }
            break
        }
        case undefined: {
            break
        }
        default: {
            action satisfies never
        }
    }
    if (moved) {
        active = threadAt({ threads, ranges }, tr.selection.head, true)
    }
    // A thread resolved is closed with it: its passage is drawn no more.
    if (threads.some((thread) => thread.id === active && thread.resolved)) {
        active = undefined
    }
    return build(state, threads, ranges, lost, active, draft)
}

// The state with every thread the ranges lack looked for again, and the decorations drawn.
function build(
    state: EditorState,
    threads: Placed[],
    ranges: Map<string, Range>,
    lost: Map<string, number>,
    active: string | undefined,
    draft: Range | undefined,
): Highlights {
    const missing = threads.filter((thread) => !ranges.has(thread.id))
    if (missing.length > 0) {
        const { text, positions } = docText(state.doc)
        for (const thread of missing) {
            const span = locate(text, thread.anchor, { approximate: !thread.resolved, near: lost.get(thread.id) })
            const range = span && rangeOf(positions, span.start, span.end)
            if (range !== undefined) {
                ranges.set(thread.id, range)
                lost.delete(thread.id)
            }
        }
    }
    const resolved = new Set(threads.filter((thread) => thread.resolved).map((thread) => thread.id))
    const decorations: Decoration[] = []
    for (const [id, range] of ranges) {
        if (!resolved.has(id)) {
            const css = id === active ? 'plan-comment plan-comment-active' : 'plan-comment'
            decorations.push(Decoration.inline(range.from, range.to, { class: css, 'data-thread': id }))
        }
    }
    if (draft !== undefined) {
        decorations.push(Decoration.inline(draft.from, draft.to, { class: 'plan-comment plan-comment-active' }))
    }
    return { threads, ranges, lost, active, draft, decorations: DecorationSet.create(state.doc, decorations) }
}

// A range through a transaction's edits: text typed at either end stays outside it, and a range whose text is all
// deleted is gone.
function mapRange(tr: Transaction, range: Range): Range | undefined {
    const from = tr.mapping.map(range.from, 1)
    const to = tr.mapping.map(range.to, -1)
    return from < to ? { from, to } : undefined
}

// The open thread whose passage holds `pos`, the innermost when passages overlap, so the one inside another can be
// reached. A click is in a passage up to its last letter; a cursor, given as `cursor`, is in it at either end too, as
// a click just after its last word puts it.
function threadAt(
    highlights: Pick<Highlights, 'threads' | 'ranges'> | undefined,
    pos: number,
    cursor = false,
): string | undefined {
    if (highlights === undefined) {
        return undefined
    }
    const resolved = new Set(highlights.threads.filter((thread) => thread.resolved).map((thread) => thread.id))
    let best: { id: string; size: number } | undefined
    for (const [id, range] of highlights.ranges) {
        if (!resolved.has(id) && range.from <= pos && (cursor ? pos <= range.to : pos < range.to)) {
            const size = range.to - range.from
            if (best === undefined || size < best.size) {
                best = { id, size }
            }
        }
    }
    return best?.id
}
