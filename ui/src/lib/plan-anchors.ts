// Where a comment on a plan sits, kept as the words it is on rather than as a position: the passage itself and a little
// of the text either side, as the W3C's text quote selector keeps it. A position goes stale with the first edit above
// it, and means nothing in the next plan the planner writes; the words can be found again in both, wherever they moved,
// so a comment stays on its passage across the operator's edits and a re-plan that keeps it. A passage that is gone is
// found nowhere, and its comment says so rather than move to something else. Whitespace counts as one space either
// way, so a passage the planner reflows is still found.

/** How much text either side of a passage an anchor keeps, to tell two copies of it apart. */
export const CONTEXT = 32

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
 * Where `anchor`'s passage is in `text`, or undefined when it is nowhere. When it is there more than once, the copy
 * whose surrounding text matches the anchor's prefix and suffix best wins, and the first of those that tie.
 */
export function locate(text: string, anchor: Anchor): Span | undefined {
    const { flat, at } = flatten(text)
    const quote = anchor.quote
    if (!quote) {
        return undefined
    }
    let best: Span | undefined
    let bestScore = -1
    for (let i = flat.indexOf(quote); i !== -1; i = flat.indexOf(quote, i + 1)) {
        const score =
            commonSuffix(flat.slice(0, i), anchor.prefix) + commonPrefix(flat.slice(i + quote.length), anchor.suffix)
        if (score > bestScore) {
            bestScore = score
            // Each index of `flat` maps back to a character of `text`; the span ends after the quote's last one.
            best = { start: at[i] ?? 0, end: (at[i + quote.length - 1] ?? 0) + 1 }
        }
    }
    return best
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
