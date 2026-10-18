import type { MemoryEntry } from '@/api/types'
import { age } from '@/lib/time'

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

/**
 * What a memory in force says of the digest that leaves it out (DESIGN §28): past its cap, it reaches no run's prompt
 * now, or would reach none at `use` while its tier is recording. A run can still find it with `canopy memory search`.
 */
export function leftOutText(served: boolean): string {
    return served ? 'left out of the prompt, past its cap' : 'would be left out at use, past its cap'
}

/** How runs used a ticket's notes in force: `read by no run`, or how many of them a run relied on. */
export function ticketNotesUsedText({ count, used }: { count: number; used: number }): string {
    return used === 0 ? 'read by no run' : `${used} of ${count} used by runs`
}

/**
 * When a proposal lapses undecided: `lapses in 3d`, in the CLI's largest whole unit, or once its time has passed,
 * `lapses at the next tick`, which is when canopy invalidates it.
 */
export function lapsesText(expiresAt: string, now: number): string {
    const left = Date.parse(expiresAt) - now
    if (left <= 0) {
        return 'lapses at the next tick'
    }
    return `lapses in ${age(new Date(now - left).toISOString(), now)}`
}

/** What a run read, when it read nothing: nothing was served while recording, which is not an empty digest. */
export function readNothingText(served: boolean): string {
    return served ? 'none' : 'none, recording only'
}

/**
 * The most characters a lesson may hold, as a proposal's (`canopy.core.memory.MAX_PROPOSAL_CHARS`): a promote is held
 * to it again on the server, past spaces at either end, which it trims.
 */
export const MAX_LESSON_CHARS = 600

/** How many characters a lesson's text counts, as the server counts them: code points, without surrounding spaces. */
export function lessonChars(text: string): number {
    // oxlint-disable-next-line typescript/no-misused-spread -- code points are what the server counts, not graphemes
    return [...text.trim()].length
}

/**
 * The repositories a promote may serve its lesson to, as `canopy memory promote --repo` takes them: null for every
 * one, offered only for a source that names none (a note, or a proposal for every repository), then the workspace's.
 * A proposal for one repository keeps it unless another is named, so its own comes first, even once the workspace map
 * has dropped it.
 */
export function repoChoices(source: Pick<MemoryEntry, 'repo'>, repos: readonly string[]): (string | null)[] {
    if (source.repo === null) {
        return [null, ...repos]
    }
    return [source.repo, ...repos.filter((r) => r !== source.repo)]
}

/** The lessons whose review date has come, the longest overdue first, as a `lesson_review` item names them. */
export function dueForReview<T extends Pick<MemoryEntry, 'id' | 'review_at'>>(lessons: readonly T[], now: number): T[] {
    return lessons
        .filter((m) => m.review_at !== null && Date.parse(m.review_at) <= now)
        .toSorted((a, b) => {
            const overdue = Date.parse(a.review_at ?? '') - Date.parse(b.review_at ?? '')
            return overdue === 0 ? a.id - b.id : overdue
        })
}

function codePoint(char: string): string {
    const point = char.codePointAt(0) ?? 0
    return `<U+${point.toString(16).toUpperCase().padStart(4, '0')}>`
}
