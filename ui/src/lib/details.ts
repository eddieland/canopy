// A review comment's `<details>` blocks, read as GitHub folds them: a block under its summary line, opened by a click.
// Only `<details>`, `<details open>`, and `<summary>` with no other attributes are read, so a tag the page drops holds
// no character the operator cannot see; any other tag stays as written. The rest is text, as `MemoryText` shows it.

import { memorySegments } from '@/lib/memory'

/** A run of a comment's text, or one of its `<details>` blocks. */
export type CommentPart = { kind: 'text'; text: string } | Details

/** A `<details>` block: its summary line, whether it was written open, and what it folds. */
export interface Details {
    /** That this part is a block. */
    kind: 'details'
    /** Its `<summary>`'s text, its formatting tags dropped, or `Details`, as GitHub says it, when it has none. */
    summary: string
    /** Whether it was written `<details open>`. */
    open: boolean
    /** What it folds: text, and the blocks nested in it. */
    parts: CommentPart[]
}

const TAG = /<details(?:[ \t\n]+open)?[ \t\n]*>|<\/details[ \t\n]*>/giu
const SUMMARY = /^[ \t\n]*<summary>([^]*?)<\/summary>/iu
// The formatting GitHub's summaries carry, dropped from the line as GitHub draws it.
const FORMAT = /<\/?(?:b|strong|i|em|code)>/giu
const OPEN_ATTRIBUTE = /[ \t\n]open/iu

/**
 * `text` as its text and its `<details>` blocks, nested as written. A tag with no partner stays text, and the blank
 * lines around a tag, which only lay it out, are dropped.
 */
export function foldDetails(text: string): CommentPart[] {
    const source = text.replaceAll('\r\n', '\n')
    return partsIn(source, 0, source.length, pairTags(source))
}

/** Whether `parts` hold a character that hides text, which `MemoryText` names once the block is open. */
export function hidesText(parts: CommentPart[]): boolean {
    return parts.some((part) =>
        part.kind === 'text' ? hasHidden(part.text) : hasHidden(part.summary) || hidesText(part.parts),
    )
}

interface Tag {
    start: number
    end: number
}

interface Pair {
    open: Tag
    close: Tag
    inner: Pair[]
}

// Each opening tag matched to its closing one, as a stack does; one left unmatched is text, and what it held belongs
// to the block around it.
function pairTags(text: string): Pair[] {
    const root: Pair[] = []
    const stack: { open: Tag; inner: Pair[] }[] = []
    for (const match of text.matchAll(TAG)) {
        const tag = { start: match.index, end: match.index + match[0].length }
        if (!match[0].startsWith('</')) {
            stack.push({ open: tag, inner: [] })
            continue
        }
        const opened = stack.pop()
        if (opened !== undefined) {
            ;(stack.at(-1)?.inner ?? root).push({ ...opened, close: tag })
        }
    }
    for (let left = stack.pop(); left !== undefined; left = stack.pop()) {
        ;(stack.at(-1)?.inner ?? root).push(...left.inner)
    }
    return root
}

// The parts between `start` and `end`, where `bounded` says a tag stands at each end, as one does inside a block.
function partsIn(text: string, start: number, end: number, pairs: Pair[], bounded = false): CommentPart[] {
    const parts: CommentPart[] = []
    let at = start
    for (const pair of pairs) {
        pushText(parts, text.slice(at, pair.open.start), bounded || at > start, true)
        parts.push(details(text, pair))
        at = pair.close.end
    }
    pushText(parts, text.slice(at, end), bounded || pairs.length > 0, bounded)
    return parts
}

function details(text: string, pair: Pair): Details {
    const bodyEnd = pair.inner[0]?.open.start ?? pair.close.start
    const summary = SUMMARY.exec(text.slice(pair.open.end, bodyEnd))
    const line = (summary?.[1] ?? '')
        .replaceAll(FORMAT, '')
        .replaceAll(/[ \t\n]+/gu, ' ')
        .trim()
    return {
        kind: 'details',
        summary: line === '' ? 'Details' : line,
        open: OPEN_ATTRIBUTE.test(text.slice(pair.open.start, pair.open.end)),
        parts: partsIn(text, pair.open.end + (summary?.[0].length ?? 0), pair.close.start, pair.inner, true),
    }
}

// Text beside a tag loses the blank lines between it and the tag, and nothing else: a space or a hidden character
// stays, so nothing the comment holds goes unseen.
function pushText(parts: CommentPart[], raw: string, afterTag: boolean, beforeTag: boolean) {
    let text = afterTag ? raw.replace(/^(?:[ \t]*\n)+/u, '') : raw
    text = beforeTag ? text.replace(/(?:\n[ \t]*)+$/u, '') : text
    if (text !== '') {
        parts.push({ kind: 'text', text })
    }
}

function hasHidden(text: string): boolean {
    return memorySegments(text, { lines: true }).some((segment) => segment.hidden)
}
