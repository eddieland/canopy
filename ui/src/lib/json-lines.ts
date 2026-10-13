// A log of JSON lines (an agent runtime's events, with whatever else it printed) as tokens a page can color. A line
// that parses as a JSON object or array is split into its keys, strings, numbers, literals, and punctuation, exactly
// as written: nothing is reformatted, so the tokens' text joined is the line. Any other line is one plain token. The
// result is data that a component renders as React text, never HTML.

/** What a piece of a line is: a JSON key, string, number, `true`/`false`/`null`, punctuation, or anything else. */
export type JsonKind = 'key' | 'string' | 'number' | 'literal' | 'punct' | 'text'

/** A piece of a line, its text as written. */
export interface JsonToken {
    /** What the piece is. `text` for whitespace in a JSON line and for the whole of any other line. */
    kind: JsonKind
    /** The piece's characters, as written. */
    text: string
}

// One JSON token: a string (a key when a colon follows it), a number, a literal, or a structural character.
const TOKEN =
    /("(?:[^"\\]|\\.)*")(?=\s*:)|("(?:[^"\\]|\\.)*")|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(true|false|null)|([{}[\],:])/gu

/** `text` as its lines, each as tokens: a line holding a JSON object or array split up, any other line whole. */
export function jsonLines(text: string): JsonToken[][] {
    return text.split('\n').map((line) => tokenize(line))
}

/** One line as tokens: split up when it is a JSON object or array, else one `text` token (none when empty). */
export function tokenize(line: string): JsonToken[] {
    if (line === '') {
        return []
    }
    if (!isJson(line)) {
        return [{ kind: 'text', text: line }]
    }
    const tokens: JsonToken[] = []
    let last = 0
    for (const match of line.matchAll(TOKEN)) {
        if (match.index > last) {
            tokens.push({ kind: 'text', text: line.slice(last, match.index) })
        }
        tokens.push({ kind: kindOf(match), text: match[0] })
        last = match.index + match[0].length
    }
    if (last < line.length) {
        tokens.push({ kind: 'text', text: line.slice(last) })
    }
    return tokens
}

function isJson(line: string): boolean {
    const start = line.trimStart()[0]
    if (start !== '{' && start !== '[') {
        return false
    }
    try {
        JSON.parse(line)
        return true
    } catch {
        return false
    }
}

function kindOf(match: RegExpMatchArray): JsonKind {
    if (match[1] !== undefined) {
        return 'key'
    }
    if (match[2] !== undefined) {
        return 'string'
    }
    if (match[3] !== undefined) {
        return 'number'
    }
    if (match[4] !== undefined) {
        return 'literal'
    }
    return 'punct'
}
