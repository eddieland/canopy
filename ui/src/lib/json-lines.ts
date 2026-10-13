// JSON in agent output as tokens a page can color: a log of JSON lines (an agent runtime's events, with whatever else
// it printed), or one block of JSON (a tool call's indented input or output). Text that parses as a JSON object or
// array is split into its keys, strings, numbers, literals, and punctuation, exactly as written: nothing is
// reformatted, so the tokens' text joined is the text. Anything else is one plain token. The result is data that a
// component renders as React text, never HTML.

/** What a piece of text is: a JSON key, string, number, `true`/`false`/`null`, punctuation, or anything else. */
export type JsonKind = 'key' | 'string' | 'number' | 'literal' | 'punct' | 'text'

/** A piece of text, as written. */
export interface JsonToken {
    /** What the piece is. `text` for whitespace in JSON, and for the whole of anything else. */
    kind: JsonKind
    /** The piece's characters, as written. */
    text: string
}

// One JSON token: a string (a key when a colon follows it), a number, a literal, or a structural character.
const TOKEN =
    /("(?:[^"\\]|\\.)*")(?=\s*:)|("(?:[^"\\]|\\.)*")|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(true|false|null)|([{}[\],:])/g

/** `text` as its lines, each as tokens: a line holding a JSON object or array split up, any other line whole. */
export function jsonLines(text: string): JsonToken[][] {
    return text.split('\n').map(tokenize)
}

/**
 * Text as tokens: split up when the whole of it is a JSON object or array, on one line or many, else one `text` token
 * (none when empty). Used for one line of a log, and for one block of JSON.
 */
export function tokenize(text: string): JsonToken[] {
    if (text === '') return []
    if (!isJson(text)) return [{ kind: 'text', text }]
    const tokens: JsonToken[] = []
    let last = 0
    for (const match of text.matchAll(TOKEN)) {
        if (match.index > last) tokens.push({ kind: 'text', text: text.slice(last, match.index) })
        tokens.push({ kind: kindOf(match), text: match[0] })
        last = match.index + match[0].length
    }
    if (last < text.length) tokens.push({ kind: 'text', text: text.slice(last) })
    return tokens
}

function isJson(text: string): boolean {
    const start = text.trimStart()[0]
    if (start !== '{' && start !== '[') return false
    try {
        JSON.parse(text)
        return true
    } catch {
        return false
    }
}

function kindOf(match: RegExpMatchArray): JsonKind {
    if (match[1] !== undefined) return 'key'
    if (match[2] !== undefined) return 'string'
    if (match[3] !== undefined) return 'number'
    if (match[4] !== undefined) return 'literal'
    return 'punct'
}
