// Agent-written text (a run's summary, a tick's, a decision's rationale) as blocks a page can lay out: paragraphs that
// keep their line breaks, lists, headings, quotes, rules, tables, and code. It reads the Markdown forms agents write
// and nothing more: the result is data that `RichText` renders as React text, never HTML. Link syntax stays
// characters; a bare URL is linked to itself by `LinkedText` (D113).

import { splitLinks } from '@/lib/links'

/** A piece of a line: plain text, `code`, **strong**, *emphasis*, or ~~struck~~. */
export interface Inline {
    /** How the piece is set. */
    kind: 'text' | 'code' | 'strong' | 'em' | 'del'
    /** The piece's text, without its markers. */
    text: string
}

/** One line of text, as its inline pieces: `Inline`'s, or another reader's (the guide's, which reads links too). */
export type Line<I = Inline> = I[]

/** One item of a list. */
export interface Item<I = Inline> {
    /**
     * How far it is nested, 0 to 3: two spaces of indent a level. A nested list of the other kind starts a list of its
     * own at its depth.
     */
    depth: number
    /** Its text: the first line, and any it continues on. */
    lines: Line<I>[]
}

/** How a table's column sets its cells, from the colons of its delimiter row; `undefined` when it names none. */
export type Align = 'left' | 'center' | 'right' | undefined

/** The class that sets a table's cell as its column's `Align` asks, for rich text and the guide alike. */
export const ALIGN: Readonly<Record<NonNullable<Align>, string>> = {
    left: 'text-left',
    center: 'text-center',
    right: 'text-right',
}

/**
 * One block of agent-written text: a paragraph, a heading (`level` is its count of `#`), a list, a quote's own blocks,
 * a rule (`---`), a table, or a code block's lines as written, with `lang`, the first word after its opening fence,
 * when it has one. A table's `align`, `head`, and every row of `rows` hold one entry a column.
 */
export type Block<I = Inline> =
    | { kind: 'paragraph'; lines: Line<I>[] }
    | { kind: 'heading'; level: number; line: Line<I> }
    | { kind: 'list'; ordered: boolean; start: number; items: Item<I>[] }
    | { kind: 'quote'; blocks: Block<I>[] }
    | { kind: 'rule' }
    | { kind: 'table'; align: Align[]; head: Line<I>[]; rows: Line<I>[][] }
    | { kind: 'code'; lines: string[]; lang?: string }

const FENCE = /^\s*(`{3,}|~{3,})/u
const HEADING = /^(#{1,6})\s+(.*)$/u
const BULLET = /^(\s*)[-*+]\s+(.*)$/u
const NUMBERED = /^(\s*)(\d{1,9})[.)]\s+(.*)$/u
const QUOTE = /^ {0,3}> ?/u
const RULE = /^ {0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$/u
// A table's delimiter row: a cell of dashes a column, each with a colon at either end or both, between pipes.
const DELIMITER = /^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$/u
const MAX_DEPTH = 3

/** `text` as blocks: a blank line ends a paragraph or a list, and a line break inside one is kept. */
export function parse(text: string): Block[] {
    return parseWith(text, inline)
}

/**
 * `text` as blocks, as `parse` reads them, with each line's pieces read by `read`. The guide's pages, canopy's own
 * text and not an agent's, read their links this way (`src/lib/guide.ts`); agent text never does.
 */
export function parseWith<I>(text: string, read: (line: string) => Line<I>): Block<I>[] {
    return blocksOf(text.replaceAll(/\r\n?/gu, '\n').split('\n'), read, 0)
}

// The blocks of `lines`, a quote's among them at `depth`: a quote nested past `MAX_DEPTH` keeps its `>` as characters.
function blocksOf<I>(lines: string[], read: (line: string) => Line<I>, depth: number): Block<I>[] {
    const blocks: Block<I>[] = []
    const quotes = depth < MAX_DEPTH
    let i = 0
    while (i < lines.length) {
        const line = lines[i] ?? ''
        const fence = FENCE.exec(line)
        if (fence) {
            const marker = fence[1] ?? '```'
            const lang = line.trimStart().slice(marker.length).trim().split(/\s/u)[0] ?? ''
            const body: string[] = []
            i += 1
            while (i < lines.length && !(lines[i] ?? '').trimStart().startsWith(marker)) {
                body.push(lines[i] ?? '')
                i += 1
            }
            blocks.push(lang === '' ? { kind: 'code', lines: body } : { kind: 'code', lines: body, lang })
            i += 1
            continue
        }
        if (line.trim() === '') {
            i += 1
            continue
        }
        if (RULE.test(line)) {
            blocks.push({ kind: 'rule' })
            i += 1
            continue
        }
        const heading = HEADING.exec(line)
        if (heading) {
            blocks.push({ kind: 'heading', level: (heading[1] ?? '#').length, line: read(heading[2] ?? '') })
            i += 1
            continue
        }
        if (quotes && QUOTE.test(line)) {
            const inner: string[] = []
            while (i < lines.length && QUOTE.test(lines[i] ?? '')) {
                inner.push((lines[i] ?? '').replace(QUOTE, ''))
                i += 1
            }
            blocks.push({ kind: 'quote', blocks: blocksOf(inner, read, depth + 1) })
            continue
        }
        const marker = listMarker(line)
        if (marker) {
            const list: Extract<Block<I>, { kind: 'list' }> = {
                kind: 'list',
                ordered: marker.ordered,
                start: marker.number,
                items: [],
            }
            while (i < lines.length) {
                const next = lines[i] ?? ''
                const item = RULE.test(next) ? null : listMarker(next)
                if (item && item.ordered === list.ordered) {
                    list.items.push({ depth: depthOf(item.indent), lines: [read(item.text)] })
                } else if (!item && next.trim() !== '' && /^\s/u.test(next) && !FENCE.test(next)) {
                    // An indented line under an item continues it.
                    list.items.at(-1)?.lines.push(read(next.trim()))
                } else {
                    break
                }
                i += 1
            }
            blocks.push(list)
            continue
        }
        const columns = tableAt(lines, i)
        if (columns > 0) {
            const table = readTable(lines, i, columns, read)
            blocks.push(table.block)
            i = table.end
            continue
        }
        const paragraph: Line<I>[] = []
        while (i < lines.length) {
            const next = lines[i] ?? ''
            if (
                next.trim() === '' ||
                FENCE.test(next) ||
                HEADING.test(next) ||
                RULE.test(next) ||
                (quotes && QUOTE.test(next)) ||
                listMarker(next) ||
                tableAt(lines, i) > 0
            ) {
                break
            }
            paragraph.push(read(next.trim()))
            i += 1
        }
        blocks.push({ kind: 'paragraph', lines: paragraph })
    }
    return blocks
}

// How many columns the table starting at `lines[at]` has: its header row and then a delimiter row of as many cells,
// each with a pipe; 0 when no table starts there.
function tableAt(lines: string[], at: number): number {
    const head = lines[at] ?? ''
    const delimiter = lines[at + 1]
    if (!head.includes('|') || delimiter === undefined || !delimiter.includes('|') || !DELIMITER.test(delimiter)) {
        return 0
    }
    const columns = cells(head).length
    return cells(delimiter).length === columns ? columns : 0
}

// The table starting at `lines[at]`, and the index of the line after it: its rows run to the first line without a pipe,
// each cut or padded to `columns` cells.
function readTable<I>(
    lines: string[],
    at: number,
    columns: number,
    read: (line: string) => Line<I>,
): { block: Block<I>; end: number } {
    const align = cells(lines[at + 1] ?? '').map((cell) => alignOf(cell))
    const row = (line: string) => Array.from({ length: columns }, (_, column) => read(cells(line)[column] ?? ''))
    const rows: Line<I>[][] = []
    let i = at + 2
    while (i < lines.length && (lines[i] ?? '').includes('|') && !FENCE.test(lines[i] ?? '')) {
        rows.push(row(lines[i] ?? ''))
        i += 1
    }
    return { block: { kind: 'table', align, head: row(lines[at] ?? ''), rows }, end: i }
}

// A table row's cells, trimmed: split on each pipe but an escaped one (`\|`), which stays in its cell as a pipe, and
// without the pipes that may open and close the row.
function cells(line: string): string[] {
    let row = line.trim()
    if (row.startsWith('|')) {
        row = row.slice(1)
    }
    if (row.endsWith('|') && !row.endsWith('\\|')) {
        row = row.slice(0, -1)
    }
    return row.split(/(?<!\\)\|/u).map((cell) => cell.trim().replaceAll('\\|', '|'))
}

function alignOf(cell: string): Align {
    const left = cell.startsWith(':')
    const right = cell.endsWith(':')
    if (left && right) {
        return 'center'
    }
    if (right) {
        return 'right'
    }
    return left ? 'left' : undefined
}

function listMarker(line: string): { ordered: boolean; number: number; indent: number; text: string } | null {
    const bullet = BULLET.exec(line)
    if (bullet) {
        return { ordered: false, number: 1, indent: (bullet[1] ?? '').length, text: bullet[2] ?? '' }
    }
    const numbered = NUMBERED.exec(line)
    if (numbered) {
        const indent = (numbered[1] ?? '').length
        return { ordered: true, number: Number(numbered[2]), indent, text: numbered[3] ?? '' }
    }
    return null
}

function depthOf(indent: number): number {
    return Math.max(0, Math.min(MAX_DEPTH, Math.floor(indent / 2)))
}

/**
 * The inline forms rich text reads, as a pattern's source for a reader to build on (the guide adds its links): `code`,
 * **strong**, ~~struck~~, and *emphasis* or _emphasis_. A run is read as one piece, so markers inside it stay
 * characters. Emphasis takes no space inside its markers' ends, nor a letter or digit outside them, so `2*3*4` and
 * `snake_case_name` stay as written.
 */
export const INLINE = [
    /`(?<code>[^`]+)`/u,
    /\*\*(?<strong>.+?)\*\*/u,
    /~~(?<del>[^\s~](?:.*?[^\s~])?)~~/u,
    /(?<![\w*])\*(?<em>[^\s*](?:[^*]*?[^\s*])?)\*(?![\w*])/u,
    /(?<![\w_])_(?<under>[^\s_](?:[^_]*?[^\s_])?)_(?![\w_])/u,
]
    .map((form) => form.source)
    .join('|')

const INLINE_PATTERN = new RegExp(INLINE, 'gu')

/** A line's code spans, strong runs, struck runs, and emphasis (`INLINE`); an unclosed marker stays as written. */
export function inline(text: string): Line {
    return pieces(text, INLINE_PATTERN)
}

/**
 * Text's `code` spans and nothing else, for a line the harness writes (an attention item's detail): asterisks and line
 * breaks stay as written, and a span never crosses a line.
 */
export function codeSpans(text: string): Line {
    return pieces(text, /`(?<code>[^`\n]+)`/gu)
}

/** The piece a match of `INLINE` reads as, or `undefined` for a match of a form it does not name. */
export function inlinePiece(match: RegExpExecArray): Inline | undefined {
    const { code, strong, del, em, under } = match.groups ?? {}
    if (code !== undefined) {
        return { kind: 'code', text: code }
    }
    if (strong !== undefined) {
        return { kind: 'strong', text: strong }
    }
    if (del !== undefined) {
        return { kind: 'del', text: del }
    }
    const emphasis = em ?? under
    return emphasis === undefined ? undefined : { kind: 'em', text: emphasis }
}

function pieces(text: string, pattern: RegExp): Line {
    const line: Line = []
    const urls = urlSpans(text)
    const inUrl = (at: number) => urls.some(([from, to]) => at >= from && at < to)
    // Text runs next to each other join, so a URL a kept marker split still links whole.
    const plain = (run: string) => {
        const previous = line.at(-1)
        if (previous?.kind === 'text') {
            previous.text += run
        } else {
            line.push({ kind: 'text', text: run })
        }
    }
    let last = 0
    for (const match of text.matchAll(pattern)) {
        if (match.index > last) {
            plain(text.slice(last, match.index))
        }
        const piece = inlinePiece(match)
        const end = match.index + match[0].length
        // An emphasis or struck marker inside a URL is part of its address (`https://x/_a_/b`), so it stays text.
        if (
            piece === undefined ||
            ((piece.kind === 'em' || piece.kind === 'del') && (inUrl(match.index) || inUrl(end - 1)))
        ) {
            plain(match[0])
        } else {
            line.push(piece)
        }
        last = end
    }
    if (last < text.length) {
        plain(text.slice(last))
    }
    return line
}

// Where each URL `LinkedText` would link sits in `text`, as its start and end.
function urlSpans(text: string): [number, number][] {
    const spans: [number, number][] = []
    let at = 0
    for (const piece of splitLinks(text)) {
        if (piece.href !== undefined) {
            spans.push([at, at + piece.text.length])
        }
        at += piece.text.length
    }
    return spans
}

/**
 * About how many characters a line of a list's row holds before it wraps. A longer line counts as the lines it would
 * wrap to, so one long paragraph folds as several short lines do.
 */
export const WRAP = 100

/**
 * How many lines `blocks` take: a list item's, a table row's, a code block's, and a rule each count, and a line of text
 * longer than `WRAP` as the lines it wraps to. A code block scrolls rather than wraps.
 */
export function lineCount(blocks: Block[]): number {
    return blocks.reduce((sum, block) => sum + linesOf(block), 0)
}

function linesOf(block: Block): number {
    switch (block.kind) {
        case 'paragraph': {
            return wrapped(block.lines)
        }
        case 'heading': {
            return 1
        }
        case 'list': {
            return block.items.reduce((sum, item) => sum + wrapped(item.lines), 0)
        }
        case 'quote': {
            return lineCount(block.blocks)
        }
        case 'rule': {
            return 1
        }
        case 'table': {
            return 1 + block.rows.length
        }
        case 'code': {
            return Math.max(1, block.lines.length)
        }
    }
}

function wrapped(lines: Line[]): number {
    return lines.reduce((sum, line) => sum + wraps(line), 0)
}

function wraps(line: Line): number {
    const length = line.reduce((sum, piece) => sum + piece.text.length, 0)
    return Math.max(1, Math.ceil(length / WRAP))
}

/**
 * The first `max` lines of `blocks` and how many lines are left out. Text one line over is shown whole: a toggle to
 * show a single line would take the line it saves.
 */
export function clamp(blocks: Block[], max: number): { blocks: Block[]; hidden: number } {
    const total = lineCount(blocks)
    if (total <= max + 1) {
        return { blocks, hidden: 0 }
    }
    return { blocks: cutBlocks(blocks, max), hidden: total - max }
}

function cutBlocks(blocks: Block[], room: number): Block[] {
    const shown: Block[] = []
    let left = room
    for (const block of blocks) {
        if (left <= 0) {
            break
        }
        shown.push(cutBlock(block, left))
        left -= linesOf(block)
    }
    return shown
}

function cutBlock(block: Block, room: number): Block {
    switch (block.kind) {
        case 'paragraph': {
            return { ...block, lines: cutLines(block.lines, room) }
        }
        case 'heading':
        case 'rule': {
            return block
        }
        case 'quote': {
            return { ...block, blocks: cutBlocks(block.blocks, room) }
        }
        case 'table': {
            // Its head counts as a line, so it shows with at least its first row when there is room for both.
            return { ...block, rows: block.rows.slice(0, room - 1) }
        }
        case 'code': {
            return { ...block, lines: block.lines.slice(0, room) }
        }
        case 'list': {
            const items: Item[] = []
            let left = room
            for (const item of block.items) {
                if (left <= 0) {
                    break
                }
                items.push({ ...item, lines: cutLines(item.lines, left) })
                left -= wrapped(item.lines)
            }
            return { ...block, items }
        }
    }
}

function cutLines(lines: Line[], room: number): Line[] {
    const kept: Line[] = []
    let left = room
    for (const line of lines) {
        if (left <= 0) {
            break
        }
        kept.push(wraps(line) <= left ? line : cutLine(line, left * WRAP))
        left -= wraps(line)
    }
    return kept
}

/**
 * The first `chars` characters of `line`, an ellipsis among them, cut where a word ends: a piece cut mid-word, a URL
 * that would link somewhere else or a code span, is left out from there.
 */
function cutLine(line: Line, chars: number): Line {
    const kept: Line = []
    let left = chars - 1
    for (const piece of line) {
        if (piece.text.length <= left) {
            kept.push(piece)
            left -= piece.text.length
            continue
        }
        if (piece.kind !== 'code') {
            const end = piece.text.slice(0, left + 1).search(/\s\S*$/u)
            const head = piece.text.slice(0, Math.max(0, end)).trimEnd()
            if (head !== '') {
                kept.push({ ...piece, text: head })
            }
        }
        break
    }
    kept.push({ kind: 'text', text: '…' })
    return kept
}
