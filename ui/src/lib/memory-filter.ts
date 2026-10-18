import type { MemoryEntry, TicketNotes } from '@/api/types'
import { memoryStand } from '@/lib/memory'
import type { TierModes } from '@/lib/memory'

/**
 * The memory page's filters (DESIGN.md, Agent memory), over what the page already read: words a memory's key, text,
 * ticket, or repository holds, or a ticket's key or title (`?q=`); the repository whose runs a proposal or lesson is
 * for (`?repo=`); and a lesson's standing (`?show=`).
 */

/** The lesson standings the page filters by: what calls for the operator. */
export const MEMORY_SHOWS = ['wrong', 'due'] as const

/** One of `MEMORY_SHOWS`. */
export type MemoryShow = (typeof MEMORY_SHOWS)[number]

/** The longest text filter kept: longer than any key, and enough of a lesson's words to find it. */
export const MEMORY_QUERY_MAX = 200

/** What the memory page is filtered by: each undefined when it filters nothing. */
export interface MemoryFilter {
    /** Words each shown memory or ticket holds. */
    q: string | undefined
    /** The repository whose runs each shown proposal or lesson is for. */
    repo: string | undefined
    /** The standing each shown lesson has. */
    show: MemoryShow | undefined
}

/** A `?show=` the page offers, else undefined, which shows every lesson. */
export function memoryShowOf(raw: unknown): MemoryShow | undefined {
    return MEMORY_SHOWS.find((s) => s === raw)
}

/** A `?q=` as the page filters by it: a string, cut to `MEMORY_QUERY_MAX`, else undefined when it holds no word. */
export function memoryQueryOf(raw: unknown): string | undefined {
    if (typeof raw !== 'string') {
        return undefined
    }
    const text = raw.slice(0, MEMORY_QUERY_MAX)
    return text.trim() === '' ? undefined : text
}

/** A `?repo=` as a repository's name, which the workspace map holds to lowercase letters, digits, and hyphens. */
export function memoryRepoOf(raw: unknown): string | undefined {
    return typeof raw === 'string' && /^[a-z0-9-]{1,64}$/u.test(raw) ? raw : undefined
}

/**
 * Whether the page shows a proposal or lesson: its key, text, ticket, or repository holds every word of `q`, in any
 * case; it is for `repo`'s runs, which a lesson for every repository is too; and, for a lesson, it stands as `show`
 * says, under the tiers' `modes`.
 */
export function memoryShown(
    entry: Pick<MemoryEntry, 'key' | 'text' | 'ticket_key' | 'repo' | 'status' | 'wrong_run_id' | 'review_at'>,
    filter: MemoryFilter,
    now: number,
    modes: TierModes,
): boolean {
    const words = `${entry.key} ${entry.text ?? ''} ${entry.ticket_key ?? ''} ${entry.repo ?? ''}`
    return (
        holdsEvery(words, filter.q) &&
        (filter.repo === undefined || entry.repo === null || entry.repo === filter.repo) &&
        (filter.show === undefined || memoryStand(entry, now, modes.lessons) === filter.show)
    )
}

/** Whether the page shows a ticket with notes: its key or title holds every word of `q`. */
export function ticketNotesShown(ticket: Pick<TicketNotes, 'ticket_key' | 'title'>, q: string | undefined): boolean {
    return holdsEvery(`${ticket.ticket_key} ${ticket.title ?? ''}`, q)
}

/** How many a panel shows, and of how many while a filter left some out: `2 of 7`. */
export function shownCount(shown: number, all: number, filtered: boolean): string {
    return filtered && shown !== all ? `${shown} of ${all}` : String(all)
}

function holdsEvery(text: string, query: string | undefined): boolean {
    const haystack = text.toLowerCase()
    const words = query?.toLowerCase().trim().split(/\s+/u) ?? []
    return words.every((word) => haystack.includes(word))
}
