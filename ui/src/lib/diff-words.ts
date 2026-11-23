import type { DiffFile, DiffHunk, DiffLine } from '@/api/types'
import type { CodeToken } from '@/lib/highlight'

/** A stretch of a line's text that differs from the line it replaced, or that replaced it, in characters. */
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

// A line longer than this, or of more words, is not compared: a minified file's line would be marked nearly whole,
// at a cost.
const MAX_LINE = 500
const MAX_WORDS = 160
// The share of the longer line's words the two must have in common, in order, to count as one line edited rather than
// one line replaced by another, which the line's own tint already says.
const ALIKE = 0.5
// A run of removed lines by one of added lines with more pairs to try than this is left unmarked.
const MAX_PAIRS = 400
// How many pairs of words a file's lines are compared over before the rest of its lines go unmarked: a diff of
// thousands of long lines, each replaced, would otherwise hold the page while it is drawn.
const MAX_COMPARED = 3_000_000
// A line's words: each run of letters, digits, and underscores, in any script, each run of spaces, and each other
// character alone.
const WORDS = /[\p{L}\p{N}\p{M}_]+|\s+|[^\p{L}\p{N}\p{M}_\s]/gu
const WORD = /^[\p{L}\p{N}_]/u
const SPACE = /^\s/u

/**
 * What changed within each line of each of `file`'s hunks, by hunk and then line: where added lines follow removed
 * ones, each removed line is paired with the next added one like it, and the words the pair does not share, in order,
 * are what changed, so two edits to a long line each show where. Undefined for a line with no pair, or one whose pair
 * shares too little with it to be the same line edited; empty for a line whose pair only added to it.
 */
export function changedWords(file: DiffFile): (Changed[] | undefined)[][] {
    const budget = { left: MAX_COMPARED }
    return file.hunks.map((hunk) => hunkChanges(hunk, budget))
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
 * A line as its parts in order, those in `changed` marked so: its `tokens` cut at each stretch's ends, each piece
 * keeping its kind, or its plain `text` when it has none. The parts spell the line, character for character.
 */
export function lineParts(
    text: string,
    tokens: readonly CodeToken[] | undefined,
    changed: readonly Changed[],
): LinePart[] {
    const cuts: [number, number, boolean][] = []
    let at = 0
    for (const { from, to } of changed) {
        cuts.push([at, from, false], [from, to, true])
        at = to
    }
    cuts.push([at, text.length, false])
    return cuts
        .filter(([from, to]) => to > from)
        .map(([from, to, marked]) => ({
            changed: marked,
            text: text.slice(from, to),
            tokens: tokens === undefined ? undefined : sliceTokens(tokens, from, to),
        }))
}

/** What is left of a file's comparisons (`MAX_COMPARED`), spent as its lines are compared. */
interface Budget {
    /** The pairs of words still to compare. */
    left: number
}

function hunkChanges(hunk: DiffHunk, budget: Budget): (Changed[] | undefined)[] {
    const { lines } = hunk
    const changes = Array.from<Changed[] | undefined>({ length: lines.length })
    let at = 0
    while (at < lines.length) {
        const dels = runOf(lines, at, 'del')
        const adds = runOf(lines, at + dels, 'add')
        // Each removed line with the first added line after the last one paired that is alike: an edit beside lines
        // only added, or only removed, still finds its pair.
        let next = at + dels
        for (let k = at; k < at + (dels * adds > MAX_PAIRS ? 0 : dels); k += 1) {
            for (let j = next; j < at + dels + adds; j += 1) {
                const pair = pairChanges(lines[k]?.text ?? '', lines[j]?.text ?? '', budget)
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

/** One word of a line, and where it is in it. */
interface Word extends Changed {
    /** Its text. */
    text: string
}

// What differs between a removed line and the added one that replaced it, on each, or undefined when the two are not
// alike. Each line is read from the end of its own indent, so a line only moved in or out has nothing marked, and one
// edited as it moved has its edit alone.
function pairChanges(wasLine: string, nowLine: string, budget: Budget): [Changed[], Changed[]] | undefined {
    if (wasLine.length > MAX_LINE || nowLine.length > MAX_LINE) {
        return undefined
    }
    const was = wordsOf(wasLine)
    const now = wordsOf(nowLine)
    if (was.length > MAX_WORDS || now.length > MAX_WORDS) {
        return undefined
    }
    const most = Math.max(weight(was), weight(now))
    // Lines of punctuation alone, a closing brace and the like, are alike only when they are the same.
    if (most === 0 && wasLine.trim() !== nowLine.trim()) {
        return undefined
    }
    // Lines that hold too few of the same words, in any order, cannot share enough in order: no need to look.
    if (inCommon(was, now) < ALIKE * most || budget.left < was.length * now.length) {
        return undefined
    }
    budget.left -= was.length * now.length
    const [wasKept, nowKept] = shared(was, now)
    if (weight(was.filter((_, i) => wasKept[i])) < ALIKE * most) {
        return undefined
    }
    return [stretches(was, wasKept), stretches(now, nowKept)]
}

// How much of two lines' words proper are the same words, whatever their order: no less than what they share in order.
function inCommon(was: readonly Word[], now: readonly Word[]): number {
    const counts = new Map<string, number>()
    for (const word of was) {
        counts.set(word.text, (counts.get(word.text) ?? 0) + 1)
    }
    let common = 0
    for (const word of now) {
        const count = counts.get(word.text) ?? 0
        if (count > 0 && WORD.test(word.text)) {
            counts.set(word.text, count - 1)
            common += word.text.length
        }
    }
    return common
}

// A line's words past its indent.
function wordsOf(line: string): Word[] {
    const indent = line.length - line.trimStart().length
    return [...line.slice(indent).matchAll(WORDS)].map((match) => ({
        text: match[0],
        from: indent + match.index,
        to: indent + match.index + match[0].length,
    }))
}

// How much of a line a set of its words is: the characters of its words proper, which say what a line is as its
// punctuation, the same on most lines of code, does not.
function weight(words: readonly Word[]): number {
    return words.reduce((sum, word) => sum + (WORD.test(word.text) ? word.text.length : 0), 0)
}

// Which words of each line are in the run of words the two share in order that weighs most, by each line's index.
// A word proper weighs by its length, as `weight` counts it, and anything else a little, so punctuation the two share
// never wins a place from a word they share, and of two runs of the same words the one that keeps more is taken.
function shared(was: readonly Word[], now: readonly Word[]): [boolean[], boolean[]] {
    const width = now.length + 1
    // The weight of the heaviest shared run of the words from `i` and from `j` on, at `i * width + j`: at most four
    // times a line's length and its words, well within 16 bits.
    const runs = new Uint16Array((was.length + 1) * width)
    for (let i = was.length - 1; i >= 0; i -= 1) {
        for (let j = now.length - 1; j >= 0; j -= 1) {
            const skipped = Math.max(runs[(i + 1) * width + j] ?? 0, runs[i * width + j + 1] ?? 0)
            const kept = was[i]?.text === now[j]?.text ? (runs[(i + 1) * width + j + 1] ?? 0) + worth(was[i]) : 0
            runs[i * width + j] = Math.max(skipped, kept)
        }
    }
    const wasKept = was.map(() => false)
    const nowKept = now.map(() => false)
    let i = 0
    let j = 0
    while (i < was.length && j < now.length) {
        const here = runs[i * width + j] ?? 0
        if (was[i]?.text === now[j]?.text && here === (runs[(i + 1) * width + j + 1] ?? 0) + worth(was[i])) {
            wasKept[i] = true
            nowKept[j] = true
            i += 1
            j += 1
        } else if (here === (runs[(i + 1) * width + j] ?? 0)) {
            i += 1
        } else {
            j += 1
        }
    }
    return [wasKept, nowKept]
}

// What keeping a word is worth to the run that keeps it.
function worth(word: Word | undefined): number {
    return word === undefined ? 0 : 1 + (WORD.test(word.text) ? 4 * word.text.length : 0)
}

// The stretches of a line its pair does not share: each run of words not kept, two runs with only spaces kept between
// them as one, so a phrase rewritten is one mark rather than a mark a word.
function stretches(words: readonly Word[], kept: readonly boolean[]): Changed[] {
    const changed: Changed[] = []
    // Whether a word proper is kept since the last stretch, which sets the next apart from it.
    let apart = true
    for (const [i, word] of words.entries()) {
        const last = changed.at(-1)
        if (kept[i]) {
            apart ||= !SPACE.test(word.text)
        } else if (last === undefined || apart) {
            changed.push({ from: word.from, to: word.to })
            apart = false
        } else {
            last.to = word.to
        }
    }
    return changed
}

// One side's range as git writes it: its first number and how many lines it has, `-4,6`, `-4` for one line, and
// `-0,0` for a side with none.
function side(sign: '-' | '+', numbers: readonly (number | null | undefined)[]): string {
    const on = numbers.filter((n) => n !== null && n !== undefined)
    // One line is its number alone.
    return on.length === 1 ? `${sign}${on[0] ?? 0}` : `${sign}${on[0] ?? 0},${on.length}`
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
