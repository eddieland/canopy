import type { MemoryEntry } from '@/api/types'

/**
 * Every character a memory's text may not hold (DESIGN §28, Bounds): Unicode's control, format, surrogate,
 * private-use, unassigned, and line and paragraph separator categories, which take in the zero-width, bidi, and tag
 * characters. Each hides text from a person that a model still reads. The same set as `canopy.core.memory_text`.
 */
const HIDDEN = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}]/u

/** A run of what a memory says: text as written, or one hidden character, named by its code point. */
export interface MemorySegment {
    /** What shows: the text, or the character's name, `<U+200B>`. */
    text: string
    /** Whether this is a hidden character, named. */
    hidden: boolean
}

/**
 * What a worker wrote, cut where a hidden character is, each named by its code point as the CLI names it: what was
 * written to the journal by hand, past the bounds, shows whole. Never Markdown or a link: a link in a note would be a
 * worker's link the operator reads as canopy's (unlike other journal text, D113).
 */
export function memorySegments(text: string): MemorySegment[] {
    const segments: MemorySegment[] = []
    let plain = ''
    for (const char of text) {
        if (!HIDDEN.test(char)) {
            plain += char
            continue
        }
        if (plain) {
            segments.push({ text: plain, hidden: false })
            plain = ''
        }
        segments.push({ text: codePoint(char), hidden: true })
    }
    if (plain) {
        segments.push({ text: plain, hidden: false })
    }
    return segments
}

/** `text` as plain text, every hidden character named, as `canopy memory list` prints it. */
export function visibleText(text: string): string {
    return memorySegments(text)
        .map((s) => s.text)
        .join('')
}

/** How runs used a memory: `read by no run`, or its use count and when it was last used. */
export function usedText(entry: Pick<MemoryEntry, 'use_count' | 'last_used_at'>): string {
    if (entry.use_count === 0 || entry.last_used_at === null) {
        return 'read by no run'
    }
    return `used by ${entry.use_count} run${entry.use_count === 1 ? '' : 's'}`
}

/** What a run read, when it read nothing: nothing was served while recording, which is not an empty digest. */
export function readNothingText(served: boolean): string {
    return served ? 'none' : 'none, recording only'
}

function codePoint(char: string): string {
    const point = char.codePointAt(0) ?? 0
    return `<U+${point.toString(16).toUpperCase().padStart(4, '0')}>`
}
