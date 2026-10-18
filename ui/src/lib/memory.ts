import type { MemoryEntry, MemoryTier } from '@/api/types'
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

/** How runs used a memory, `used by 3 runs`, or nothing while no run has relied on it: a row says what happened. */
export function usedText(entry: Pick<MemoryEntry, 'use_count' | 'last_used_at'>): string | null {
    if (entry.use_count === 0 || entry.last_used_at === null) {
        return null
    }
    return `used by ${entry.use_count} run${entry.use_count === 1 ? '' : 's'}`
}

/**
 * Where a memory stands, in the words a row leads with: its status, but a lesson in force that a run reported wrong is
 * `wrong`, and one past its review date `due`, since each calls for the operator; and one in force while its tier only
 * records is `recorded`, since no run reads it, so it never reads as in force (DESIGN §28).
 */
export type MemoryStand = MemoryEntry['status'] | 'wrong' | 'due' | 'recorded'

/** Each tier's mode, as the loop's state carries it, which says whether a memory in force reaches a run. */
export interface TierModes {
    /** Ticket notes' mode. */
    ticket_notes: MemoryTier['mode']
    /** Lessons' and proposals' mode. */
    lessons: MemoryTier['mode']
}

/** The mode of the tier `scope` is in: a note's is ticket notes', a proposal's and a lesson's is lessons'. */
export function tierMode(scope: MemoryEntry['scope'], modes: TierModes): MemoryTier['mode'] {
    return scope === 'ticket' ? modes.ticket_notes : modes.lessons
}

/**
 * Where `entry` stands at `now`, as `MemoryStand` says: recorded before anything a run would report, since no run read
 * it, then wrong before due, since a wrong lesson misleads every run. With no `mode`, its tier is taken as in use.
 */
export function memoryStand(
    entry: Pick<MemoryEntry, 'status' | 'wrong_run_id' | 'review_at'>,
    now: number,
    mode: MemoryTier['mode'] = 'use',
): MemoryStand {
    if (entry.status !== 'active') {
        return entry.status
    }
    if (mode !== 'use') {
        return 'recorded'
    }
    if (entry.wrong_run_id !== null) {
        return 'wrong'
    }
    if (entry.review_at !== null && Date.parse(entry.review_at) <= now) {
        return 'due'
    }
    return 'active'
}

/** When a lesson comes up for review: `review in 82d`, or once that has passed `review overdue 3d`. */
export function reviewText(reviewAt: string, now: number): string {
    const left = Date.parse(reviewAt) - now
    if (left > 0) {
        return `review in ${age(new Date(now - left).toISOString(), now)}`
    }
    return `review overdue ${age(reviewAt, now)}`
}

/**
 * What a memory in force says of the digest that leaves it out (DESIGN §28): past its cap, it reaches no run's prompt
 * now, or would reach none at `use` while its tier is recording. A run can still find it with `canopy memory search`.
 */
export function leftOutText(served: boolean): string {
    return served ? 'left out of the prompt, past its cap' : 'would be left out at use, past its cap'
}

/** How many of a ticket's notes in force a run relied on, `3 of 4 used by runs`, or nothing while none was. */
export function ticketNotesUsedText({ count, used }: { count: number; used: number }): string | null {
    return used === 0 ? null : `${used} of ${count} used by runs`
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

/** How long a proposal has left undecided, as its standing says it: `3d left`, or `lapsing` once that has passed. */
export function leftText(expiresAt: string, now: number): string {
    const left = Date.parse(expiresAt) - now
    return left <= 0 ? 'lapsing' : `${age(new Date(now - left).toISOString(), now)} left`
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
