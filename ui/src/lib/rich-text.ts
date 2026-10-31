// Agent-written text (a run's summary, a tick's, a decision's rationale) as blocks a page can lay out: paragraphs that
// keep their line breaks, lists, headings, and code. It reads the few Markdown forms agents write and nothing more:
// the result is data that `RichText` renders as React text, never HTML. Link syntax stays characters; a bare URL is
// linked to itself by `LinkedText` (D113).

/** A piece of a line: plain text, `code`, or **strong**; code inside a strong run is a code piece flagged `strong`. */
export interface Inline {
    /** How the piece is set. */
    kind: 'text' | 'code' | 'strong'
    /** The piece's text, without its markers. */
    text: string
    /** On a code piece, that it sits inside a strong run: `**the `api` service**`. */
    strong?: true
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

/**
 * One block of agent-written text: a paragraph, a heading (`level` is its count of `#`), a list, or a code block's
 * lines as written, with `lang`, the first word after its opening fence, when it has one.
 */
export type Block<I = Inline> =
    | { kind: 'paragraph'; lines: Line<I>[] }
    | { kind: 'heading'; level: number; line: Line<I> }
    | { kind: 'list'; ordered: boolean; start: number; items: Item<I>[] }
    | { kind: 'code'; lines: string[]; lang?: string }

const FENCE = /^\s*(`{3,}|~{3,})/u
const HEADING = /^(#{1,6})\s+(.*)$/u
const BULLET = /^(\s*)[-*+]\s+(.*)$/u
const NUMBERED = /^(\s*)(\d{1,9})[.)]\s+(.*)$/u
const MAX_DEPTH = 3
const CODE_SPAN = /`([^`\n]+)`/gu

/** `text` as blocks: a blank line ends a paragraph or a list, and a line break inside one is kept. */
export function parse(text: string): Block[] {
    return parseWith(text, inline)
}

/**
 * `text` as blocks, as `parse` reads them, with each line's pieces read by `read`. The guide's pages, canopy's own
 * text and not an agent's, read their links this way (`src/lib/guide.ts`); agent text never does.
 */
export function parseWith<I>(text: string, read: (line: string) => Line<I>): Block<I>[] {
    const blocks: Block<I>[] = []
    const lines = text.replaceAll(/\r\n?/gu, '\n').split('\n')
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
        const heading = HEADING.exec(line)
        if (heading) {
            blocks.push({ kind: 'heading', level: (heading[1] ?? '#').length, line: read(heading[2] ?? '') })
            i += 1
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
                const item = listMarker(next)
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
        const paragraph: Line<I>[] = []
        while (i < lines.length) {
            const next = lines[i] ?? ''
            if (next.trim() === '' || FENCE.test(next) || HEADING.test(next) || listMarker(next)) {
                break
            }
            paragraph.push(read(next.trim()))
            i += 1
        }
        blocks.push({ kind: 'paragraph', lines: paragraph })
    }
    return blocks
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

/** A line's `code` spans and **strong** runs, code inside strong too; anything unclosed stays as it was written. */
export function inline(text: string): Line {
    return inlineWith(text, /\*\*(.+?)\*\*/dgu, ([, strong]) => strongRun(strong ?? ''))
}

/**
 * `text` with each match of `pattern` read by `read`, from the groups the match holds, and the text between matches
 * read for its `code` spans. A code span binds tighter than any match, as CommonMark's does: a match never starts or
 * ends inside one, so `**a `b** c`` is code after `**a `, not strong. `pattern` takes the `d` and `g` flags. The guide
 * reads its strong runs and links this way (`src/lib/guide.ts`).
 */
export function inlineWith<I>(
    text: string,
    pattern: RegExp,
    read: (groups: readonly (string | undefined)[]) => I[],
): (I | Inline)[] {
    // Blanking the spans out keeps every offset, so a match in the blanked text is at the same place in the text.
    const blanked = text.replaceAll(CODE_SPAN, (span) => ' '.repeat(span.length))
    const line: (I | Inline)[] = []
    let last = 0
    for (const match of blanked.matchAll(pattern)) {
        const groups = (match.indices ?? []).map((at: [number, number] | undefined) =>
            at === undefined ? undefined : text.slice(at[0], at[1]),
        )
        line.push(...codeSpans(text.slice(last, match.index)), ...read(groups))
        last = match.index + match[0].length
    }
    line.push(...codeSpans(text.slice(last)))
    return line
}

/**
 * A **strong** run's text, without its markers, as its pieces: strong text, and its `code` spans flagged `strong`. The
 * guide's reader shares it (`src/lib/guide.ts`).
 */
export function strongRun(text: string): Line {
    return codeSpans(text).map((piece) =>
        piece.kind === 'code' ? { kind: 'code', text: piece.text, strong: true } : { kind: 'strong', text: piece.text },
    )
}

/**
 * Text's `code` spans and nothing else, for a line the harness writes (an attention item's detail): asterisks and line
 * breaks stay as written, and a span never crosses a line.
 */
export function codeSpans(text: string): Line {
    const line: Line = []
    let last = 0
    for (const match of text.matchAll(CODE_SPAN)) {
        if (match.index > last) {
            line.push({ kind: 'text', text: text.slice(last, match.index) })
        }
        line.push({ kind: 'code', text: match[1] ?? '' })
        last = match.index + match[0].length
    }
    if (last < text.length) {
        line.push({ kind: 'text', text: text.slice(last) })
    }
    return line
}

/**
 * About how many characters a line of a list's row holds before it wraps. A longer line counts as the lines it would
 * wrap to, so one long paragraph folds as several short lines do.
 */
export const WRAP = 100

/**
 * How many lines `blocks` take: a list item's or a code block's each count, and a line of text longer than `WRAP` as
 * the lines it wraps to. A code block scrolls rather than wraps.
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
    const shown: Block[] = []
    let room = max
    for (const block of blocks) {
        if (room <= 0) {
            break
        }
        shown.push(cutBlock(block, room))
        room -= linesOf(block)
    }
    return { blocks: shown, hidden: total - max }
}

function cutBlock(block: Block, room: number): Block {
    switch (block.kind) {
        case 'paragraph': {
            return { ...block, lines: cutLines(block.lines, room) }
        }
        case 'heading': {
            return block
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
