// Agent-written text (a run's summary, a tick's, a decision's rationale) as blocks a page can lay out: paragraphs that
// keep their line breaks, lists, headings, and code. It reads the few Markdown forms agents write and nothing more:
// the result is data that `RichText` renders as React text, never HTML. Link syntax stays characters; a bare URL is
// linked to itself by `LinkedText` (D113).

/** A piece of a line: plain text, `code`, or **strong**. */
export interface Inline {
    /** How the piece is set. */
    kind: 'text' | 'code' | 'strong'
    /** The piece's text, without its markers. */
    text: string
}

/** One line of text, as its inline pieces. */
export type Line = Inline[]

/** One item of a list. */
export interface Item {
    /**
     * How far it is nested, 0 to 3: two spaces of indent a level. A nested list of the other kind starts a list of its
     * own at its depth.
     */
    depth: number
    /** Its text: the first line, and any it continues on. */
    lines: Line[]
}

/** One block of agent-written text: a paragraph, a heading, a list, or a code block's lines as written. */
export type Block =
    | { kind: 'paragraph'; lines: Line[] }
    | { kind: 'heading'; line: Line }
    | { kind: 'list'; ordered: boolean; start: number; items: Item[] }
    | { kind: 'code'; lines: string[] }

const FENCE = /^\s*(`{3,}|~{3,})/u
const HEADING = /^#{1,6}\s+(.*)$/u
const BULLET = /^(\s*)[-*+]\s+(.*)$/u
const NUMBERED = /^(\s*)(\d{1,9})[.)]\s+(.*)$/u
const MAX_DEPTH = 3

/** `text` as blocks: a blank line ends a paragraph or a list, and a line break inside one is kept. */
export function parse(text: string): Block[] {
    const blocks: Block[] = []
    const lines = text.replaceAll(/\r\n?/gu, '\n').split('\n')
    let i = 0
    while (i < lines.length) {
        const line = lines[i] ?? ''
        const fence = FENCE.exec(line)
        if (fence) {
            const marker = fence[1] ?? '```'
            const body: string[] = []
            i += 1
            while (i < lines.length && !(lines[i] ?? '').trimStart().startsWith(marker)) {
                body.push(lines[i] ?? '')
                i += 1
            }
            blocks.push({ kind: 'code', lines: body })
            i += 1
            continue
        }
        if (line.trim() === '') {
            i += 1
            continue
        }
        const heading = HEADING.exec(line)
        if (heading) {
            blocks.push({ kind: 'heading', line: inline(heading[1] ?? '') })
            i += 1
            continue
        }
        const marker = listMarker(line)
        if (marker) {
            const list: Block & { kind: 'list' } = {
                kind: 'list',
                ordered: marker.ordered,
                start: marker.number,
                items: [],
            }
            while (i < lines.length) {
                const next = lines[i] ?? ''
                const item = listMarker(next)
                if (item && item.ordered === list.ordered) {
                    list.items.push({ depth: depthOf(item.indent), lines: [inline(item.text)] })
                } else if (!item && next.trim() !== '' && /^\s/u.test(next) && !FENCE.test(next)) {
                    // An indented line under an item continues it.
                    list.items.at(-1)?.lines.push(inline(next.trim()))
                } else {
                    break
                }
                i += 1
            }
            blocks.push(list)
            continue
        }
        const paragraph: Line[] = []
        while (i < lines.length) {
            const next = lines[i] ?? ''
            if (next.trim() === '' || FENCE.test(next) || HEADING.test(next) || listMarker(next)) {
                break
            }
            paragraph.push(inline(next.trim()))
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

/** A line's `code` spans and **strong** runs; anything unclosed stays as it was written. */
export function inline(text: string): Line {
    const pieces: Line = []
    const pattern = /`([^`]+)`|\*\*(.+?)\*\*/gu
    let last = 0
    for (const match of text.matchAll(pattern)) {
        if (match.index > last) {
            pieces.push({ kind: 'text', text: text.slice(last, match.index) })
        }
        if (match[1] === undefined) {
            pieces.push({ kind: 'strong', text: match[2] ?? '' })
        } else {
            pieces.push({ kind: 'code', text: match[1] })
        }
        last = match.index + match[0].length
    }
    if (last < text.length) {
        pieces.push({ kind: 'text', text: text.slice(last) })
    }
    return pieces
}

/** How many lines `blocks` take, before wrapping: a list item's or a code block's each count. */
export function lineCount(blocks: Block[]): number {
    return blocks.reduce((sum, block) => sum + linesOf(block), 0)
}

function linesOf(block: Block): number {
    switch (block.kind) {
        case 'paragraph': {
            return block.lines.length
        }
        case 'heading': {
            return 1
        }
        case 'list': {
            return block.items.reduce((sum, item) => sum + item.lines.length, 0)
        }
        case 'code': {
            return Math.max(1, block.lines.length)
        }
    }
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
        const cut = cutBlock(block, room)
        shown.push(cut)
        room -= linesOf(cut)
    }
    return { blocks: shown, hidden: total - max }
}

function cutBlock(block: Block, room: number): Block {
    switch (block.kind) {
        case 'paragraph': {
            return { ...block, lines: block.lines.slice(0, room) }
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
                items.push({ ...item, lines: item.lines.slice(0, left) })
                left -= item.lines.length
            }
            return { ...block, items }
        }
    }
}
