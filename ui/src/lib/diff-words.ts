import type { DiffFile, DiffHunk, DiffLine } from '@/api/types'
import type { CodeToken } from '@/lib/highlight'

/** The stretch of a line's text that differs from the line it replaced, or that replaced it, in characters. */
export interface Changed {
    /** Where the stretch starts in the line's text. */
    from: number
    /** One past where it ends. */
    to: number
}

/** A piece of a line as the page draws it: its tokens, or its plain text, and whether it is the changed stretch. */
export interface LinePart {
    /** Whether this piece is the stretch that changed. */
    changed: boolean
    /** Its plain text, for a line with no tokens. */
    text: string
    /** Its tokens, for a highlighted line. */
    tokens: CodeToken[] | undefined
}

// A line longer than this is not compared: a minified file's line would be marked nearly whole, at a cost.
const MAX_LINE = 500
// The share of the longer line the two must have in common, at their ends, to count as one line edited rather than
// one line replaced by another, which the line's own tint already says.
const ALIKE = 0.4
// A run of removed lines by one of added lines with more pairs to try than this is left unmarked.
const MAX_PAIRS = 400
const WORD = /\w/u

/**
 * What changed within each line of each of `file`'s hunks, by hunk and then line: where added lines follow removed
 * ones, each removed line is paired with the next added one like it, and the pair's differing middle, widened to whole
 * words, is what changed, so an edit to a long line shows where.
 * Undefined for a line with no pair, one whose pair shares too little with it to be the same line edited, and one
 * with nothing to mark, as a removed line whose pair only added to it.
 */
export function changedWords(file: DiffFile): (Changed | undefined)[][] {
    return file.hunks.map((hunk) => hunkChanges(hunk))
}

/** A hunk's ranges as git writes them, `-4,6 +4,8`, from its lines' numbers: where it starts and how far it runs. */
export function hunkRange(hunk: DiffHunk): string {
    return `${side(
        '-',
        hunk.lines.map((line) => line.old),
    )} ${side(
        '+',
        hunk.lines.map((line) => line.new),
    )}`
}

/** How many lines a file's diff adds and removes. */
export function fileLines(file: DiffFile): { added: number; removed: number } {
    let added = 0
    let removed = 0
    for (const hunk of file.hunks) {
        for (const line of hunk.lines) {
            if (line.kind === 'add') {
                added += 1
            } else if (line.kind === 'del') {
                removed += 1
            }
        }
    }
    return { added, removed }
}

/**
 * A line as up to three parts, the middle one its `changed` stretch: its `tokens` cut at the stretch's ends, each
 * piece keeping its kind, or its plain `text` when it has none. The parts spell the line, character for character.
 */
export function lineParts(text: string, tokens: readonly CodeToken[] | undefined, changed: Changed): LinePart[] {
    const cuts: [number, number, boolean][] = [
        [0, changed.from, false],
        [changed.from, changed.to, true],
        [changed.to, text.length, false],
    ]
    return cuts
        .filter(([from, to]) => to > from)
        .map(([from, to, marked]) => ({
            changed: marked,
            text: text.slice(from, to),
            tokens: tokens === undefined ? undefined : sliceTokens(tokens, from, to),
        }))
}

function hunkChanges(hunk: DiffHunk): (Changed | undefined)[] {
    const { lines } = hunk
    const changes = Array.from<Changed | undefined>({ length: lines.length })
    let at = 0
    while (at < lines.length) {
        const dels = runOf(lines, at, 'del')
        const adds = runOf(lines, at + dels, 'add')
        // Each removed line with the first added line after the last one paired that is alike: an edit beside lines
        // only added, or only removed, still finds its pair.
        let next = at + dels
        for (let k = at; k < at + (dels * adds > MAX_PAIRS ? 0 : dels); k += 1) {
            for (let j = next; j < at + dels + adds; j += 1) {
                const pair = pairChanges(lines[k]?.text ?? '', lines[j]?.text ?? '')
                if (pair !== undefined) {
                    changes[k] = pair[0]
                    changes[j] = pair[1]
                    next = j + 1
                    break
                }
            }
        }
        at += Math.max(1, dels + adds)
    }
    return changes
}

// How many lines of `kind` run from `from`.
function runOf(lines: readonly DiffLine[], from: number, kind: DiffLine['kind']): number {
    let n = 0
    while (lines[from + n]?.kind === kind) {
        n += 1
    }
    return n
}

// What differs between a removed line and the added one that replaced it, on each; undefined for a side with nothing
// to mark, and for both when the two are not alike. Each line is read from the end of its own indent, so a line only
// moved in or out has nothing marked, and one edited as it moved has its edit alone.
function pairChanges(wasLine: string, nowLine: string): [Changed | undefined, Changed | undefined] | undefined {
    if (wasLine.length > MAX_LINE || nowLine.length > MAX_LINE) {
        return undefined
    }
    const was = wasLine.trimStart()
    const now = nowLine.trimStart()
    const short = Math.min(was.length, now.length)
    let head = 0
    while (head < short && was[head] === now[head]) {
        head += 1
    }
    let tail = 0
    while (tail < short - head && was.at(-1 - tail) === now.at(-1 - tail)) {
        tail += 1
    }
    if (head + tail < ALIKE * Math.max(was.trimEnd().length, now.trimEnd().length)) {
        return undefined
    }
    // Never half of a character written as two code units, which the two may share.
    if (lowSurrogate(was, head)) {
        head -= 1
    }
    if (lowSurrogate(was, was.length - tail)) {
        tail -= 1
    }
    // An end that cuts a word on either line moves out to the word's end on both: what they share there is the same.
    if (cutsWord(was, head) || cutsWord(now, head)) {
        while (inWord(was, head - 1)) {
            head -= 1
        }
    }
    if (cutsWord(was, was.length - tail) || cutsWord(now, now.length - tail)) {
        while (tail > 0 && inWord(was, was.length - tail)) {
            tail -= 1
        }
    }
    return [
        stretch(wasLine.length - was.length, head, was.length - tail),
        stretch(nowLine.length - now.length, head, now.length - tail),
    ]
}

// A line's changed stretch, past its `indent`, or undefined when it has none: the other line only added here.
function stretch(indent: number, from: number, to: number): Changed | undefined {
    return to > from ? { from: indent + from, to: indent + to } : undefined
}

function cutsWord(text: string, at: number): boolean {
    return inWord(text, at - 1) && inWord(text, at)
}

function inWord(text: string, at: number): boolean {
    const char = text[at]
    return char !== undefined && WORD.test(char)
}

function lowSurrogate(text: string, at: number): boolean {
    const code = text.codePointAt(at) ?? 0
    return code >= 56_320 && code <= 57_343
}

// One side's range: its first number and how many lines it has, `-4,6`; `-0,0` for a side with none, as git writes.
function side(sign: '-' | '+', numbers: readonly (number | null | undefined)[]): string {
    const on = numbers.filter((n) => n !== null && n !== undefined)
    return `${sign}${on[0] ?? 0},${on.length}`
}

function sliceTokens(tokens: readonly CodeToken[], from: number, to: number): CodeToken[] {
    const cut: CodeToken[] = []
    let at = 0
    for (const token of tokens) {
        const end = at + token.text.length
        if (end > from && at < to) {
            cut.push({ kind: token.kind, text: token.text.slice(Math.max(0, from - at), to - at) })
        }
        at = end
    }
    return cut
}
