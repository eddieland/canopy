import type { SearchHit, SearchSource } from '@/api/types'

// The server's bounds on a query (core/search.py): it answers anything else with a 422, so the UI never sends it.
/** The fewest characters a query may have. */
export const SEARCH_MIN = 2
/** The most characters a query may have. */
export const SEARCH_MAX = 200
/** The most distinct words a query may have. */
export const SEARCH_WORDS = 8
/** How long the box waits after the last keystroke before it searches. */
export const SEARCH_DEBOUNCE_MS = 250

/** The order the server reads its sources in, and each one's panel. `satisfies` fails the typecheck on a new source. */
export const SEARCH_SOURCES = [
    'ticket',
    'task',
    'message',
    'chore_run',
    'decision',
    'tick',
] as const satisfies readonly SearchSource[]

/** Each source's panel title. */
export const SOURCE_LABEL: Record<SearchSource, string> = {
    ticket: 'Tickets',
    task: 'Tasks',
    message: 'Messages',
    chore_run: 'Chore runs',
    decision: 'Decisions',
    tick: 'Ticks',
}

/**
 * A query as the search page keeps it in `?q=`: its whitespace collapsed, or undefined when the server would refuse it.
 * The router parses a search param as JSON first, so `?q=123` arrives as a number.
 */
export function searchQueryOf(raw: unknown): string | undefined {
    if (typeof raw !== 'string' && typeof raw !== 'number') {
        return undefined
    }
    const text = String(raw).split(/\s+/u).filter(Boolean).join(' ')
    if (text.length < SEARCH_MIN || text.length > SEARCH_MAX) {
        return undefined
    }
    return new Set(text.split(' ')).size > SEARCH_WORDS ? undefined : text
}

/** One piece of a snippet: text, and whether it is one of the search's words. */
export interface Piece {
    /** The piece's characters, as they were in the snippet. */
    text: string
    /** Whether it matches one of the search's words. */
    mark: boolean
}

/**
 * `text` in pieces, each match of any of `words` marked, letters in either case. Longer words are tried first, so a
 * word inside another is marked as part of the longer one.
 */
export function marked(text: string, words: readonly string[]): Piece[] {
    const terms = words.filter(Boolean).toSorted((a, b) => b.length - a.length)
    if (terms.length === 0) {
        return text ? [{ text, mark: false }] : []
    }
    const pattern = new RegExp(`(${terms.map((w) => literal(w)).join('|')})`, 'iu')
    // A split on a capturing group puts each match at an odd index.
    return text
        .split(pattern)
        .map((part, i) => ({ text: part, mark: i % 2 === 1 }))
        .filter((p) => p.text !== '')
}

/**
 * Tokens (a tool call's colored JSON, say) cut where `marked` would cut their joined text, each piece keeping its
 * token's fields: a match marked across the tokens it spans, so `"key": "val` is found in a key and a string alike.
 */
export function markedTokens<T extends { text: string }>(
    tokens: readonly T[],
    words: readonly string[],
): (T & { mark: boolean })[] {
    const pieces = marked(tokens.map((t) => t.text).join(''), words)
    const out: (T & { mark: boolean })[] = []
    // Where the walk is in the pieces: which one, and how far into it.
    let at = 0
    let into = 0
    for (const token of tokens) {
        let rest = token.text
        while (rest !== '') {
            const piece = pieces[at]
            if (piece === undefined) {
                break
            }
            const take = Math.min(rest.length, piece.text.length - into)
            out.push({ ...token, text: rest.slice(0, take), mark: piece.mark })
            rest = rest.slice(take)
            into += take
            if (into === piece.text.length) {
                at += 1
                into = 0
            }
        }
    }
    return out
}

/** `text` as a regular expression that matches it character for character. */
export function literal(text: string): string {
    return text.replaceAll(/[.*+?^${}()|[\]\\]/gu, '\\$&')
}

/** The hits of each source that has any, in the server's order. */
export function bySource(hits: readonly SearchHit[]): [SearchSource, SearchHit[]][] {
    return SEARCH_SOURCES.map((s): [SearchSource, SearchHit[]] => [s, hits.filter((h) => h.source === s)]).filter(
        ([, found]) => found.length > 0,
    )
}

/** Whether a key press is the search box's shortcut: `/` with no modifier, typed anywhere but a text field. */
export function isSearchShortcut(
    event: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'altKey'>,
    target: unknown,
) {
    if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) {
        return false
    }
    if (!(target instanceof HTMLElement)) {
        return true
    }
    return !(target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
}
