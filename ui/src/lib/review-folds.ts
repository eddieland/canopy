import type { DiffFile } from '@/api/types'

/**
 * How much of a review's diff the page draws before the operator asks for more. A diff at the server's bounds (500
 * files, 30,000 lines) drawn whole is over 150,000 elements: seconds to a first paint, and seconds more for every
 * click on the page after. So a diff over `page` lines draws the `context` lines either side of each finding's line,
 * then whole files, in order, while they fit in `page`, then the first lines of the rest with what is left; each fold
 * in what it leaves out shows `step` more lines a click.
 */
export const DIFF_BUDGET = { page: 2000, context: 10, step: 500 } as const

// A count grouped by thousands (`13,029`), the same in every browser's locale.
const GROUPED = new Intl.NumberFormat('en-US')

/** A run of a file's lines, by their index across its hunks in order, from `from` up to and not including `to`. */
export interface Span {
    /** The first line's index in the file. */
    from: number
    /** One past the last line's index in the file. */
    to: number
}

/**
 * One piece of a file as the page draws it, in order: a hunk's header, a run of a hunk's lines, or a fold of lines it
 * hides, which may run across hunks, their headers hidden with them.
 */
export type Piece = HunkPiece | LinesPiece | FoldPiece

/** A hunk's `@@` header. */
export interface HunkPiece {
    /** What the piece is. */
    kind: 'hunk'
    /** The hunk's index in the file. */
    hunk: number
}

/** A run of one hunk's lines, shown. */
export interface LinesPiece {
    /** What the piece is. */
    kind: 'lines'
    /** The hunk's index in the file. */
    hunk: number
    /** The first line's index in the hunk. */
    from: number
    /** One past the last line's index in the hunk. */
    to: number
}

/** Lines hidden until the operator asks for them. */
export interface FoldPiece {
    /** What the piece is. */
    kind: 'fold'
    /** The lines it hides, by their index in the file. */
    span: Span
}

/** How many lines a file's hunks hold. */
export function lineCount(file: DiffFile): number {
    return file.hunks.reduce((sum, hunk) => sum + hunk.lines.length, 0)
}

/**
 * The lines of each file the page draws at first, as spans in order, by the file's index. Every line of a diff within
 * the budget. Else the lines around each finding's line; then whole files, in order, while they fit in what is left;
 * then, with what is left after that, the first lines of the files not drawn whole, in order.
 * `anchored` maps a file's index to the new-side line numbers findings sit on, as `placeFindings` sorts them.
 */
export function shownAtFirst(
    files: readonly DiffFile[],
    anchored: ReadonlyMap<number, ReadonlyMap<number, unknown>>,
): Span[][] {
    const counts = files.map((file) => lineCount(file))
    if (counts.reduce((sum, n) => sum + n, 0) <= DIFF_BUDGET.page) {
        return counts.map((n) => (n > 0 ? [{ from: 0, to: n }] : []))
    }
    const shown: Span[][] = files.map((file, i) => {
        let spans: Span[] = []
        for (const at of findingIndexes(file, anchored.get(i)?.keys() ?? [])) {
            const from = Math.max(0, at - DIFF_BUDGET.context)
            const to = Math.min(counts[i] ?? 0, at + DIFF_BUDGET.context + 1)
            spans = reveal(spans, { from, to })
        }
        return spans
    })
    let left = DIFF_BUDGET.page - shown.reduce((sum, spans) => sum + size(spans), 0)
    counts.forEach((n, i) => {
        const more = n - size(shown[i] ?? [])
        if (more > 0 && more <= left) {
            left -= more
            shown[i] = [{ from: 0, to: n }]
        }
    })
    counts.forEach((n, i) => {
        const spans = shown[i] ?? []
        const more = Math.min(left, n - size(spans))
        if (more > 0) {
            left -= more
            shown[i] = reveal(spans, { from: 0, to: prefixEnd(spans, more) })
        }
    })
    return shown
}

/** `spans` with `span` shown too: in order, and merged where they touch or overlap. */
export function reveal(spans: readonly Span[], span: Span): Span[] {
    const merged: Span[] = []
    for (const s of [...spans, span].toSorted((a, b) => a.from - b.from)) {
        const last = merged.at(-1)
        if (last !== undefined && s.from <= last.to) {
            last.to = Math.max(last.to, s.to)
        } else if (s.to > s.from) {
            merged.push({ ...s })
        }
    }
    return merged
}

/** What a fold's button says it does: `Show 60 hidden lines`, or `Show 500 of 13,029 hidden lines` past a step. */
export function foldLabel(fold: Span): string {
    const hidden = fold.to - fold.from
    const next = nextStep(fold).to - fold.from
    if (next === hidden) {
        return `Show ${GROUPED.format(hidden)} hidden ${hidden === 1 ? 'line' : 'lines'}`
    }
    return `Show ${GROUPED.format(next)} of ${GROUPED.format(hidden)} hidden lines`
}

/** What the line above a folded diff says: how many of its lines the page draws at first, and how a fold shows more. */
export function foldedText(drawn: number, total: number): string {
    return (
        `A long diff: the page shows ${GROUPED.format(drawn)} of its ${GROUPED.format(total)} lines at first, those ` +
        'around each finding among them. A fold shows more.'
    )
}

/**
 * What a file's panel says while the operator has folded it: `120 lines folded away`, or `120 lines and 2 findings
 * folded away` when cards sit on it. `cards` names what they are, one and many (`['finding', 'findings']`).
 */
export function fileFoldedText(lines: number, count: number, cards: readonly [string, string]): string {
    const counted = `${GROUPED.format(lines)} ${lines === 1 ? 'line' : 'lines'}`
    if (count === 0) {
        return `${counted} folded away`
    }
    return `${counted} and ${count} ${count === 1 ? cards[0] : cards[1]} folded away`
}

/** The lines a click on `fold` shows: its first `DIFF_BUDGET.step`. */
export function nextStep(fold: Span): Span {
    return { from: fold.from, to: Math.min(fold.to, fold.from + DIFF_BUDGET.step) }
}

/**
 * A file as the page draws it, given the spans of its lines shown: each hunk with a line shown has its header, then its
 * lines in runs, shown or folded. A fold at a hunk's end runs on through the hunks after it with nothing shown, so a
 * file with nothing shown is one fold.
 */
export function pieces(file: DiffFile, shown: readonly Span[]): Piece[] {
    const out: Piece[] = []
    let fold: Span | null = null
    let start = 0
    for (const [h, hunk] of file.hunks.entries()) {
        const end = start + hunk.lines.length
        const runs = runsOf(shown, start, end)
        if (runs.some((r) => r.shown)) {
            if (fold !== null) {
                out.push({ kind: 'fold', span: fold })
                fold = null
            }
            out.push({ kind: 'hunk', hunk: h })
            for (const r of runs) {
                if (r.shown) {
                    out.push({ kind: 'lines', hunk: h, from: r.from - start, to: r.to - start })
                } else if (r.to === end) {
                    fold = { from: r.from, to: r.to }
                } else {
                    out.push({ kind: 'fold', span: { from: r.from, to: r.to } })
                }
            }
        } else if (end > start) {
            fold = fold === null ? { from: start, to: end } : { from: fold.from, to: end }
        }
        start = end
    }
    if (fold !== null) {
        out.push({ kind: 'fold', span: fold })
    }
    return out
}

/** The lines from `start` up to `end` in runs, each shown or not by `shown`. */
function runsOf(shown: readonly Span[], start: number, end: number): (Span & { shown: boolean })[] {
    const runs: (Span & { shown: boolean })[] = []
    let at = start
    for (const s of shown) {
        const from = Math.max(s.from, start)
        const to = Math.min(s.to, end)
        if (to <= from) {
            continue
        }
        if (from > at) {
            runs.push({ from: at, to: from, shown: false })
        }
        runs.push({ from, to, shown: true })
        at = to
    }
    if (at < end) {
        runs.push({ from: at, to: end, shown: false })
    }
    return runs
}

/** How many lines `spans` hold. */
function size(spans: readonly Span[]): number {
    return spans.reduce((sum, s) => sum + s.to - s.from, 0)
}

/** Where a span from a file's first line ends that shows `more` lines `spans` does not, `spans` in order. */
function prefixEnd(spans: readonly Span[], more: number): number {
    let end = 0
    let wanted = more
    for (const s of spans) {
        if (s.from - end >= wanted) {
            break
        }
        wanted -= s.from - end
        end = s.to
    }
    return end + wanted
}

/** The index in `file` of each line a finding sits on: on the new side, and not a deleted line, as the page puts it. */
function findingIndexes(file: DiffFile, lines: Iterable<number>): number[] {
    const wanted = new Set(lines)
    const found: number[] = []
    let i = 0
    for (const hunk of file.hunks) {
        for (const line of hunk.lines) {
            if (line.new !== null && line.kind !== 'del' && wanted.has(line.new)) {
                found.push(i)
            }
            i += 1
        }
    }
    return found
}
