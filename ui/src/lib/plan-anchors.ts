// Where a comment on a plan sits, kept as the words it is on rather than as a position: the passage itself and a little
// of the text either side, as the W3C's text quote selector keeps it. A position goes stale with the first edit above
// it, and means nothing in the next plan the planner writes; the words can be found again in both, wherever they moved,
// so a comment stays on its passage across the operator's edits and a re-plan that keeps it. Whitespace counts as one
// space either way, so a passage the planner reflows is still found.
//
// The words are looked for exactly first. An open comment's passage not there word for word is then looked for
// approximately, as Hypothesis re-anchors an annotation: every place the passage's words appear with a few edits
// (Myers' bit-parallel search, bounded by Ukkonen's cutoff, so a long plan costs a pass or two over its text), each
// scored on how much of the passage and the text either side of it survive, and the place where it was last seen
// breaking a tie. A passage lightly reworded keeps its comment; one rewritten or deleted is found nowhere, and its
// comment says so rather than move to something else.

/**
 * The character an inline atom (a verbatim tag or image, `src/lib/plan-schema.ts`) stands as in a plan's text, so an
 * anchor can span it.
 */
export const ATOM = '\uFFFC'

/** How much text either side of a passage an anchor keeps, to tell two copies of it apart. */
export const CONTEXT = 32

// How much of an anchor, its passage and the text either side together, must survive for an approximate match to
// stand: three quarters of its characters, counting each edit as one lost. A long passage carries itself; a short one
// moves only where the text around it held.
const KEPT = 0.75

// The share of a passage's own characters that may be edits in an approximate match: past a third, the passage was
// rewritten, not reworded, however well the text around it held.
const QUOTE_EDITS = 1 / 3

// The most edits an approximate match of a long passage may have, which also bounds the search's work on it.
const MAX_EDITS = 128

// How much the distance from where the passage was last seen, as a share of the plan's length, takes off a match's
// score: little enough that it only tells apart places that match alike, as copies of the same words do.
const NEARNESS = 0.02

// The most places an approximate search scores, the fewest edits first and the nearest of those: a short passage with
// one edit allowed can match hundreds of places in a long plan, and every one past these is as poor a match.
const MAX_CANDIDATES = 256

// The bits a word of the bit-parallel search holds, each a row of the edit-distance table.
const WORD = 32

/** A comment's passage, as its words and the text either side of them, each with its whitespace collapsed. */
export interface Anchor {
    /** The passage's own text. Never empty. */
    quote: string
    /** Up to `CONTEXT` characters before it, the nearest last. */
    prefix: string
    /** Up to `CONTEXT` characters after it, the nearest first. */
    suffix: string
}

/** A span of a text, from `start` up to but not including `end`. */
export interface Span {
    /** The index of its first character. */
    start: number
    /** The index after its last character. */
    end: number
}

/** How `locate` looks for a passage beyond its exact words. */
export interface Looking {
    /**
     * Whether a passage not found word for word is looked for approximately, as a light rewording of it. Off, only
     * its exact words find it.
     */
    approximate?: boolean
    /** Where the passage was last seen, as an index of the text: of places that match alike, the nearest wins. */
    near?: number | undefined
}

/** Where a pattern matches a text approximately: the index after the match's last character, and its edits. */
export interface Match {
    /** The index of the text after the match's last character. */
    end: number
    /** How many characters inserted, deleted, or changed turn the pattern into the match. */
    edits: number
}

/**
 * The anchor for the characters of `text` from `start` to `end`, its whitespace trimmed from both ends, or undefined
 * when the span holds nothing but whitespace.
 */
export function anchorAt(text: string, start: number, end: number): Anchor | undefined {
    let from = Math.max(0, start)
    let to = Math.min(text.length, end)
    while (from < to && isSpace(text[from])) {
        from += 1
    }
    while (to > from && isSpace(text[to - 1])) {
        to -= 1
    }
    if (from >= to) {
        return undefined
    }
    const before = collapse(text.slice(Math.max(0, from - CONTEXT * 2), from))
    const after = collapse(text.slice(to, to + CONTEXT * 2))
    return {
        quote: collapse(text.slice(from, to)),
        prefix: before.slice(-CONTEXT),
        suffix: after.slice(0, CONTEXT),
    }
}

/**
 * Where `anchor`'s passage is in `text`, or undefined when it is nowhere. Its exact words win wherever they are: when
 * they are there more than once, the copy whose surrounding text matches the anchor's prefix and suffix best, then the
 * one nearest `near`, then the first. With `approximate`, a passage not there exactly is the best place its words are
 * with at most `QUOTE_EDITS` of them edited, up to `MAX_EDITS`, where at least `KEPT` of the anchor survives.
 */
export function locate(text: string, anchor: Anchor, { approximate = false, near }: Looking = {}): Span | undefined {
    const quote = anchor.quote
    if (!quote) {
        return undefined
    }
    const { flat, at } = flatten(text)
    const found = exactly(flat, at, anchor, near) ?? (approximate ? approximately(flat, at, anchor, near) : undefined)
    // Each index of `flat` maps back to a character of `text`; the span ends after the passage's last one.
    return found && { start: at[found.start] ?? 0, end: (at[found.end - 1] ?? 0) + 1 }
}

/**
 * Every place `pattern` ends in `text` with at most `max` edits, in order, by Myers' bit-parallel algorithm with
 * Ukkonen's cutoff: the work is a pass over `text` a word of the pattern's rows at a time, and only as many words as
 * can still be within `max`. With `anchored`, a match must start at the text's first character, as a search back from
 * a match's end needs; otherwise it starts anywhere.
 */
export function approximateMatches(text: string, pattern: string, max: number, anchored = false): Match[] {
    const rows = pattern.length
    const matches: Match[] = []
    if (rows === 0 || max < 0) {
        return matches
    }
    const words = Math.ceil(rows / WORD)
    const lastWord = words - 1
    // For each character of the pattern, a bit for each row it is on, word by word.
    const peq = new Map<number, Int32Array>()
    for (let i = 0; i < rows; i += 1) {
        const code = unit(pattern, i)
        let bits = peq.get(code)
        if (bits === undefined) {
            bits = new Int32Array(words)
            peq.set(code, bits)
        }
        bits[i >> 5] = (bits[i >> 5] ?? 0) | (1 << (i & 31))
    }
    const none = new Int32Array(words)
    // Each word's vertical deltas, the rows that go up by one (`plus`) and down by one (`minus`), and the value of the
    // edit-distance table at its last row, for the column just read.
    const plus = new Int32Array(words).fill(-1)
    const minus = new Int32Array(words)
    const score = new Int32Array(words)
    const lastRow = (word: number) => (word === lastWord ? rows - lastWord * WORD : WORD)
    // The last word worked, past which every row is more than `max`.
    let top = Math.min(lastWord, Math.max(0, Math.ceil(max / WORD) - 1))
    for (let w = 0; w <= top; w += 1) {
        score[w] = w * WORD + lastRow(w)
    }
    // Advances word `w` by one column of the text, given the change along the row above it, and returns the change
    // along its own last row.
    const advance = (w: number, eq: Int32Array, carry: number): number => {
        const pv = plus[w] ?? 0
        const mv = minus[w] ?? 0
        const negative = carry < 0 ? 1 : 0
        const match = (eq[w] ?? 0) | negative
        const xv = match | mv
        const xh = (((match & pv) + pv) ^ pv) | match
        let ph = mv | ~(xh | pv)
        let mh = pv & xh
        const bit = 1 << ((lastRow(w) - 1) & 31)
        const out = (ph & bit) === 0 ? ((mh & bit) === 0 ? 0 : -1) : 1
        ph = (ph << 1) | (carry > 0 ? 1 : 0)
        mh = (mh << 1) | negative
        plus[w] = mh | ~(xv | ph)
        minus[w] = ph & xv
        return out
    }
    const first = anchored ? 1 : 0
    for (let j = 0; j < text.length; j += 1) {
        const eq = peq.get(unit(text, j)) ?? none
        let carry = first
        for (let w = 0; w <= top; w += 1) {
            carry = advance(w, eq, carry)
            score[w] = (score[w] ?? 0) + carry
        }
        const below = top + 1
        // The next word's first row can come within `max` only by a match on it, or by the row above going down.
        if (top < lastWord && (score[top] ?? 0) - carry <= max && (((eq[below] ?? 0) & 1) !== 0 || carry < 0)) {
            plus[below] = -1
            minus[below] = 0
            score[below] = (score[top] ?? 0) + lastRow(below) - carry + advance(below, eq, carry)
            top = below
        } else {
            while (top > 0 && (score[top] ?? 0) >= max + WORD) {
                top -= 1
            }
        }
        const edits = score[lastWord] ?? 0
        if (top === lastWord && edits <= max) {
            matches.push({ end: j + 1, edits })
        }
    }
    return matches
}

/** `text` with each run of whitespace one space, and its ends trimmed. */
export function collapse(text: string): string {
    return text.replaceAll(/\s+/gu, ' ').trim()
}

function isSpace(char: string | undefined): boolean {
    return char !== undefined && /\s/u.test(char)
}

// `text` with each run of whitespace one space, as `collapse` does but untrimmed, and for each of its characters the
// index in `text` it came from: a run's space maps to the run's first character.
function flatten(text: string): { flat: string; at: number[] } {
    let flat = ''
    const at: number[] = []
    let space = false
    for (let i = 0; i < text.length; i += 1) {
        const char = text[i] ?? ''
        if (/\s/u.test(char)) {
            if (!space) {
                flat += ' '
                at.push(i)
            }
            space = true
        } else {
            flat += char
            at.push(i)
            space = false
        }
    }
    return { flat, at }
}

// The best copy of the anchor's exact words in `flat`, by how much of its prefix and suffix each copy has, then by how
// near `near` it is, then the first.
function exactly(flat: string, at: number[], anchor: Anchor, near: number | undefined): Span | undefined {
    const quote = anchor.quote
    let best: Span | undefined
    let bestScore = -1
    let bestDistance = Infinity
    for (let i = flat.indexOf(quote); i !== -1; i = flat.indexOf(quote, i + 1)) {
        const score =
            commonSuffix(flat.slice(0, i), anchor.prefix) + commonPrefix(flat.slice(i + quote.length), anchor.suffix)
        const distance = near === undefined ? 0 : Math.abs((at[i] ?? 0) - near)
        if (score > bestScore || (score === bestScore && distance < bestDistance)) {
            bestScore = score
            bestDistance = distance
            best = { start: i, end: i + quote.length }
        }
    }
    return best
}

// How many characters `text` ends with of what `prefix` ends with, compared from the end back.
function commonSuffix(text: string, prefix: string): number {
    const before = text.trimEnd()
    const want = prefix.trimEnd()
    let n = 0
    while (n < before.length && n < want.length && before[before.length - 1 - n] === want[want.length - 1 - n]) {
        n += 1
    }
    return n
}

// How many characters `text` starts with of what `suffix` starts with.
function commonPrefix(text: string, suffix: string): number {
    const after = text.trimStart()
    const want = suffix.trimStart()
    let n = 0
    while (n < after.length && n < want.length && after[n] === want[n]) {
        n += 1
    }
    return n
}

// The best place in `flat` the anchor's words are with a few edits, where enough of the anchor survives (`KEPT`), or
// undefined when there is none. Each place scores the share of the anchor's characters it keeps, less a little for its
// distance from `near`.
function approximately(flat: string, at: number[], anchor: Anchor, near: number | undefined): Span | undefined {
    const quote = anchor.quote
    const max = Math.min(MAX_EDITS, Math.floor(quote.length * QUOTE_EDITS))
    if (max < 1) {
        return undefined
    }
    const size = Math.max(1, (at.at(-1) ?? 0) + 1)
    const away = (start: number) => (near === undefined ? 0 : Math.abs((at[Math.max(0, start)] ?? 0) - near) / size)
    const whole = quote.length + anchor.prefix.length + anchor.suffix.length
    // The most of the anchor a match may lose and still stand.
    const most = Math.floor((1 - KEPT) * whole)
    const beside = sides(flat, anchor, most)
    const runs = runsOf(approximateMatches(flat, quote, max))
        .map((run) => ({ run, fewest: Math.min(...run.map((match) => match.edits)) }))
        .toSorted((a, b) =>
            a.fewest === b.fewest ? away(a.run[0]?.end ?? 0) - away(b.run[0]?.end ?? 0) : a.fewest - b.fewest,
        )
        .slice(0, MAX_CANDIDATES)
    let best: Span | undefined
    let bestScore = -Infinity
    for (const { run, fewest } of runs) {
        // A first look, from where the match with the fewest edits ends and would start unedited, passes over a place
        // whose surroundings are far from the anchor's without weighing every end and start it could have: those lie
        // within `max` of it, and each character a boundary moves changes what the text beside it loses by one.
        const first = cheapest(run, (match) => match.edits)
        const glance = first && fewest + beside.after(first.end) + beside.before(first.end - quote.length)
        if (glance === undefined || glance > most + 3 * max + 2) {
            continue
        }
        // Where a match ends is chosen with the text after it, and where it starts with the text before: edit distance
        // alone would rather leave a word the planner added at a passage's end outside it than count it.
        const end = cheapest(run, (match) => withBeside(match.edits, beside.after(match.end), quote.length))
        if (end === undefined) {
            continue
        }
        const { start, edits } = startOf(flat, quote, end.end, end.edits + max, beside.before)
        const span = wholeWords(flat, trimmed(flat, { start, end: end.end }))
        const lost = edits + beside.before(start) + beside.after(end.end)
        const score = 1 - lost / whole - NEARNESS * away(span.start)
        if (lost <= most && score > bestScore) {
            bestScore = score
            best = span
        }
    }
    return best
}

// How much of the anchor's prefix is lost before a match that starts at a given index of `flat`, and of its suffix
// after one that ends at a given index, counted no further than past `most`.
function sides(
    flat: string,
    anchor: Anchor,
    most: number,
): { before: (start: number) => number; after: (end: number) => number } {
    const prefix = reversed(anchor.prefix.trimEnd())
    const suffix = anchor.suffix.trimStart()
    // Each is asked of the same index more than once, as a match's ends and starts are weighed and then scored.
    const befores = new Map<number, number>()
    const afters = new Map<number, number>()
    return {
        before: (start) =>
            remembered(befores, start, () =>
                contextEdits(reversed(flat.slice(Math.max(0, start - CONTEXT * 2), start).trimEnd()), prefix, most),
            ),
        after: (end) =>
            remembered(afters, end, () => contextEdits(flat.slice(end, end + CONTEXT * 2).trimStart(), suffix, most)),
    }
}

// `known`'s value for `key`, worked out by `work` and kept there the first time it is asked for.
function remembered(known: Map<number, number>, key: number, work: () => number): number {
    let value = known.get(key)
    if (value === undefined) {
        value = work()
        known.set(key, value)
    }
    return value
}

// Matches grouped by the ends that follow one another, as the characters either side of a good match match too with
// an edit or two more: each group is one place.
function runsOf(matches: Match[]): Match[][] {
    const runs: Match[][] = []
    let last = -2
    for (const match of matches) {
        if (match.end === last + 1) {
            runs.at(-1)?.push(match)
        } else {
            runs.push([match])
        }
        last = match.end
    }
    return runs
}

// The item of `items` that costs least, the first of those, or undefined when there are none.
function cheapest<T>(items: Iterable<T>, cost: (item: T) => number): T | undefined {
    let best: T | undefined
    let least = Infinity
    for (const item of items) {
        const each = cost(item)
        if (each < least) {
            least = each
            best = item
        }
    }
    return best
}

// What a match of a passage `length` long costs with the text beside it: its own edits and the context's, and a
// fraction under one more for its own, so of two that cost alike, the one whose words match better wins.
function withBeside(edits: number, beside: number, length: number): number {
    return edits + beside + edits / (length + 1)
}

// Where the match of `quote` that ends at `end` starts, and its edits: a search back from its end for the starts with
// at most `max` edits, of which the one that costs least with the text before it (`before`), then the one that makes
// the match nearest the quote's length.
function startOf(
    flat: string,
    quote: string,
    end: number,
    max: number,
    before: (start: number) => number,
): { start: number; edits: number } {
    const from = Math.max(0, end - quote.length - max)
    const backs = approximateMatches(reversed(flat.slice(from, end)), reversed(quote), max, true).map((back) => ({
        start: end - back.end,
        edits: back.edits,
    }))
    const nearest = backs.toSorted(
        (a, b) => Math.abs(end - a.start - quote.length) - Math.abs(end - b.start - quote.length),
    )
    const fallback = { start: Math.max(0, end - quote.length), edits: max }
    return cheapest(nearest, (back) => withBeside(back.edits, before(back.start), quote.length)) ?? fallback
}

// `span` without the space either end of it may have, since an anchor's words are trimmed.
function trimmed(flat: string, span: Span): Span {
    let { start, end } = span
    while (start < end - 1 && flat[start] === ' ') {
        start += 1
    }
    while (end > start + 1 && flat[end - 1] === ' ') {
        end -= 1
    }
    return { start, end }
}

// `span` widened to whole words where it ends inside one, so a reworded passage is never drawn from the middle of a
// word: `CVS` for a `CSV` whose letters swapped, not the `CV` its fewest edits are.
function wholeWords(flat: string, span: Span): Span {
    let { start, end } = span
    while (start > 0 && isWordChar(flat[start - 1]) && isWordChar(flat[start])) {
        start -= 1
    }
    while (end < flat.length && isWordChar(flat[end - 1]) && isWordChar(flat[end])) {
        end += 1
    }
    return { start, end }
}

function isWordChar(char: string | undefined): boolean {
    return char !== undefined && /[\p{L}\p{N}_]/u.test(char)
}

// How many edits turn `want` into the nearest end of `have`, at most `want`'s length, and counted only to one past
// `most`. `have` is the text beside a match, read away from it, and `want` the anchor's, read the same way, so text the
// far end gained or lost costs nothing, and an anchor that had none there (a passage at the plan's start) costs none.
function contextEdits(have: string, want: string, most: number): number {
    // `row[j]` is the edits that turn what of `want` is read so far into the first `j` characters of `have`, and
    // `least` the fewest of them: whatever of `have` is past the end `want` best turns into is the far text.
    const row = new Int32Array(have.length + 1)
    for (let j = 0; j <= have.length; j += 1) {
        row[j] = j
    }
    let least = 0
    for (let i = 1; i <= want.length; i += 1) {
        const char = unit(want, i - 1)
        let diagonal = i - 1
        let left = i
        row[0] = i
        least = i
        for (let j = 1; j <= have.length; j += 1) {
            const up = row[j] ?? 0
            const cell = Math.min(diagonal + (char === unit(have, j - 1) ? 0 : 1), up + 1, left + 1)
            row[j] = cell
            diagonal = up
            left = cell
            least = Math.min(least, cell)
        }
        // A row's least never falls in the rows after it: past `most`, the count is past what any match may lose.
        if (least > most) {
            return Math.min(want.length, most + 1)
        }
    }
    return Math.min(want.length, least)
}

// `text` back to front, a UTF-16 unit at a time, as `unit` reads it.
function reversed(text: string): string {
    let back = ''
    for (let i = text.length - 1; i >= 0; i -= 1) {
        back += text[i] ?? ''
    }
    return back
}

// The UTF-16 unit of `text` at `i`. The searches compare units rather than code points: a string's indices count units,
// and so do a match's ends, and a pair reversed for the search back compares the same as in its passage.
function unit(text: string, i: number): number {
    // oxlint-disable-next-line unicorn/prefer-code-point -- a code point would not line up with the indices (above)
    return text.charCodeAt(i)
}
