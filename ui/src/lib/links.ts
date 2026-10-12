/** A run of journal text: plain, or a URL that is shown as a link to itself. */
export type Piece = { text: string; href?: undefined } | { text: string; href: string }

// An http or https URL starting at a word boundary, up to whitespace or a character that cannot end one unescaped.
const URL_START = /\bhttps?:\/\/[^\s<>"'`]+/giu

// Punctuation that ends a sentence more often than a URL: dropped from the end of a match.
const TRAILING = new Set(['.', ',', ';', ':', '!', '?', '*', '_'])
const CLOSING: Record<string, string> = { ')': '(', ']': '[', '}': '{' }

/**
 * Split untrusted text into plain pieces and the http and https URLs in it (D112). A link's text is the URL exactly
 * as written, so the page never shows one destination and opens another; nothing else in the text becomes markup.
 * Sentence punctuation after a URL, and a closing bracket the URL did not open, stay text.
 */
export function splitLinks(text: string): Piece[] {
    const pieces: Piece[] = []
    let plain = 0
    for (const match of text.matchAll(URL_START)) {
        const url = trim(match[0])
        if (!URL.canParse(url) || new URL(url).hostname === '') continue
        if (match.index > plain) pieces.push({ text: text.slice(plain, match.index) })
        pieces.push({ text: url, href: url })
        plain = match.index + url.length
    }
    if (plain < text.length) pieces.push({ text: text.slice(plain) })
    return pieces
}

function trim(url: string): string {
    let end = url.length
    for (;;) {
        const last = url.charAt(end - 1)
        const opening = CLOSING[last]
        if (TRAILING.has(last)) end -= 1
        else if (opening !== undefined && count(url.slice(0, end), opening) < count(url.slice(0, end), last)) end -= 1
        else return url.slice(0, end)
    }
}

function count(text: string, char: string): number {
    return text.split(char).length - 1
}
