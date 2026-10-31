// Formatting Markdown as text, for a field the operator writes to an agent in (`MarkdownField`): each function reads
// the text and its selection and returns one edit, never the text whole, so the field can hand it to the browser and
// keep its undo. It writes only the forms `RichText` draws (`src/lib/rich-text.ts`), the few agents write and read:
// **strong**, `code`, a fenced code block, a list, and a heading. What the operator writes then reads in the
// conversation as it did in the field's preview.

/** Where the selection sits in the text, as a textarea's `selectionStart` and `selectionEnd`. */
export interface Selection {
    /** Where it starts, in UTF-16 code units. */
    start: number
    /** Where it ends; the same as `start` for a cursor. */
    end: number
}

/** One change to the text: what goes in place of `from` to `to`, and the selection after it. */
export interface Edit {
    /** Where the text replaced starts. */
    from: number
    /** Where it ends; the same as `from` for an insertion. */
    to: number
    /** What takes its place. */
    insert: string
    /** The selection once the edit is made. */
    selection: Selection
}

/** A run of text marked on both sides: **strong** or `code`. */
export type Mark = 'strong' | 'code'

/** What a line can start with: a bullet, a number, or a heading's `##`. */
export type LinePrefix = 'bullet' | 'ordered' | 'heading'

/** `text` with `edit` made. */
export function applyEdit(text: string, edit: Edit): string {
    return text.slice(0, edit.from) + edit.insert + text.slice(edit.to)
}

const MARKERS: Record<Mark, string> = { strong: '**', code: '`' }

/**
 * Marks the selection strong or as code, or unmarks it when it already is, its markers inside the selection or just
 * outside. A cursor gets an empty pair to type into, or leaves one it sits in. Whitespace at the selection's ends stays
 * outside the markers, since `** word**` is not strong. Code over several lines is a code block (`toggleCodeBlock`).
 */
export function toggleMark(text: string, selection: Selection, mark: Mark): Edit {
    const marker = MARKERS[mark]
    const { start, end } = trimmed(text, selection)
    if (mark === 'code' && text.slice(start, end).includes('\n')) {
        return toggleCodeBlock(text, selection)
    }
    const size = marker.length
    if (text.slice(start - size, start) === marker && text.slice(end, end + size) === marker) {
        const inner = text.slice(start, end)
        return { from: start - size, to: end + size, insert: inner, selection: shifted(start, end, -size) }
    }
    const inner = text.slice(start, end)
    if (end - start >= 2 * size && inner.startsWith(marker) && inner.endsWith(marker)) {
        const bare = inner.slice(size, -size)
        return { from: start, to: end, insert: bare, selection: { start, end: start + bare.length } }
    }
    return { from: start, to: end, insert: marker + inner + marker, selection: shifted(start, end, size) }
}

/**
 * Fences the selection's lines as a code block, or unfences them when they sit in one whose fences are the lines either
 * side.
 * A cursor on an empty line opens an empty block with the cursor inside it.
 */
export function toggleCodeBlock(text: string, selection: Selection): Edit {
    const from = lineStart(text, selection.start)
    const to = lineEnd(text, selection.end)
    const before = from === 0 ? undefined : lineStart(text, from - 1)
    const after = to === text.length ? undefined : lineEnd(text, to + 1)
    if (
        before !== undefined &&
        after !== undefined &&
        isFence(text.slice(before, from - 1)) &&
        isFence(text.slice(to + 1, after)) &&
        // The fences either side are one block's only when the lines sit inside it: text between two blocks has a
        // closing fence above and an opening one below.
        inCodeBlock(text, from)
    ) {
        const body = text.slice(from, to)
        return { from: before, to: after, insert: body, selection: { start: before, end: before + body.length } }
    }
    const body = text.slice(from, to)
    const insert = `\`\`\`\n${body}\n\`\`\``
    const start = from + 4
    return {
        from,
        to,
        insert,
        selection:
            selection.start === selection.end
                ? { start: selection.start + 4, end: selection.start + 4 }
                : { start, end: start + body.length },
    }
}

/**
 * Starts each of the selection's lines with a bullet, a number (1., 2., and on), or `## `, in place of any other of the
 * three; or, when every line already starts so, takes it off. A blank line among several keeps nothing, as a list or a
 * heading cannot hold it. A cursor stays where it was in its line's words; a selection selects the lines changed.
 */
export function toggleLinePrefix(text: string, selection: Selection, prefix: LinePrefix): Edit {
    const from = lineStart(text, selection.start)
    const to = lineEnd(text, selection.end)
    const lines = text.slice(from, to).split('\n')
    const several = lines.length > 1
    const parsed = lines.map((line) => parseLine(line))
    const marked = parsed.filter((line) => !several || line.words !== '' || line.prefix !== undefined)
    const off = marked.length > 0 && marked.every((line) => line.prefix === prefix)
    let number = 0
    const changed = parsed.map((line) => {
        if (off || (several && line.words === '' && line.prefix === undefined)) {
            return line.indent + line.words
        }
        number += 1
        return line.indent + prefixText(prefix, number) + line.words
    })
    const insert = changed.join('\n')
    if (selection.start === selection.end) {
        const first = parsed[0]
        const old = first === undefined ? 0 : first.indent.length + first.marker.length
        const now = (changed[0] ?? '').length - (first?.words.length ?? 0)
        const cursor = Math.max(from + now, selection.start + now - old)
        return { from, to, insert, selection: { start: cursor, end: cursor } }
    }
    return { from, to, insert, selection: { start: from, end: from + insert.length } }
}

/**
 * What Enter does in a list item, at a cursor after its marker: a new item under it, the next number for a numbered
 * one, at the same indent; or, on an item with no words, an end to the list, its marker taken off. Undefined anywhere
 * else, inside a code block included, where Enter makes a new line as always.
 */
export function continueList(text: string, selection: Selection): Edit | undefined {
    if (selection.start !== selection.end) {
        return undefined
    }
    const cursor = selection.start
    const from = lineStart(text, cursor)
    if (inCodeBlock(text, from)) {
        return undefined
    }
    const line = parseLine(text.slice(from, lineEnd(text, cursor)))
    // A marker with nothing after it, `2026.`, is a word that looks like one, not an item.
    if (
        line.prefix === undefined ||
        line.prefix === 'heading' ||
        !/\s$/u.test(line.marker) ||
        cursor - from < line.indent.length + line.marker.length
    ) {
        return undefined
    }
    if (line.words.trim() === '') {
        const to = lineEnd(text, cursor)
        return { from, to, insert: '', selection: { start: from, end: from } }
    }
    const next = line.prefix === 'ordered' ? `${line.number + 1}${line.delimiter} ` : `${line.marker.trimEnd()} `
    const insert = `\n${line.indent}${next}`
    const after = cursor + insert.length
    return { from: cursor, to: cursor, insert, selection: { start: after, end: after } }
}

// A line as its indent, the list or heading marker after it with its space, and the words after that.
interface ParsedLine {
    indent: string
    marker: string
    prefix: LinePrefix | undefined
    // A numbered item's number and what follows it, `.` or `)`.
    number: number
    delimiter: string
    words: string
}

const ITEM = /^(\s*)(?:([-*+])|(\d{1,9})([.)]))(\s+|$)(.*)$/u
const HEADING = /^(\s*)(#{1,6})(\s+|$)(.*)$/u

function parseLine(line: string): ParsedLine {
    const item = ITEM.exec(line)
    if (item) {
        const [, indent = '', bullet, digits, delimiter = '.', space = '', words = ''] = item
        const marker = (bullet ?? `${digits ?? ''}${delimiter}`) + space
        if (bullet !== undefined) {
            return { indent, marker, prefix: 'bullet', number: 0, delimiter: '', words }
        }
        return { indent, marker, prefix: 'ordered', number: Number(digits), delimiter, words }
    }
    const heading = HEADING.exec(line)
    if (heading) {
        const [, indent = '', hashes = '', space = '', words = ''] = heading
        return { indent, marker: hashes + space, prefix: 'heading', number: 0, delimiter: '', words }
    }
    const indent = /^\s*/u.exec(line)?.[0] ?? ''
    return { indent, marker: '', prefix: undefined, number: 0, delimiter: '', words: line.slice(indent.length) }
}

function prefixText(prefix: LinePrefix, number: number): string {
    switch (prefix) {
        case 'bullet': {
            return '- '
        }
        case 'ordered': {
            return `${number}. `
        }
        case 'heading': {
            return '## '
        }
    }
}

// The selection without the whitespace at its ends, as a double-click selects a word and the space after it.
function trimmed(text: string, { start, end }: Selection): Selection {
    let from = start
    let to = end
    while (from < to && /\s/u.test(text[from] ?? '')) {
        from += 1
    }
    while (to > from && /\s/u.test(text[to - 1] ?? '')) {
        to -= 1
    }
    return { start: from, end: to }
}

function shifted(start: number, end: number, by: number): Selection {
    return { start: start + by, end: end + by }
}

function lineStart(text: string, at: number): number {
    return text.lastIndexOf('\n', at - 1) + 1
}

function lineEnd(text: string, at: number): number {
    const end = text.indexOf('\n', at)
    return end === -1 ? text.length : end
}

const FENCE = /^\s*(`{3,}|~{3,})/u

function isFence(line: string): boolean {
    return FENCE.test(line)
}

// Whether the line starting at `from` is inside a fenced code block: an odd count of fences above it.
function inCodeBlock(text: string, from: number): boolean {
    return (
        text
            .slice(0, from)
            .split('\n')
            .filter((line) => isFence(line)).length %
            2 ===
        1
    )
}
