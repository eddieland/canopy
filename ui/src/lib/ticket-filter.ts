import type { TicketSummary } from '@/api/types'

/**
 * The tickets page's filters (DESIGN.md, the tickets list): where a ticket stands (`?show=`), and words its key or
 * title holds (`?q=`). Both go over the list the server sent, its newest by activity.
 */

/** Where a ticket stands, as the page filters by it: not done, a run working it now, waiting on a reply, or done. */
export const TICKET_SHOWS = ['open', 'working', 'waiting', 'done'] as const

/** One of `TICKET_SHOWS`. */
export type TicketShow = (typeof TICKET_SHOWS)[number]

/** Each filter in the page's words: what waits on the operator's reply is `waiting on you` wherever it shows. */
export const TICKET_SHOW_LABEL: Record<TicketShow, string> = {
    open: 'open',
    working: 'working',
    waiting: 'waiting on you',
    done: 'done',
}

/** The longest text filter kept: longer than any key and title a row shows. */
export const TICKET_QUERY_MAX = 200

/** A `?show=` the page offers, else undefined, which shows every ticket. */
export function ticketShowOf(raw: unknown): TicketShow | undefined {
    return TICKET_SHOWS.find((s) => s === raw)
}

/** A `?q=` as the page filters by it: a string, cut to `TICKET_QUERY_MAX`, else undefined when it holds no word. */
export function ticketQueryOf(raw: unknown): string | undefined {
    if (typeof raw !== 'string') {
        return undefined
    }
    const text = raw.slice(0, TICKET_QUERY_MAX)
    return text.trim() === '' ? undefined : text
}

/**
 * Whether the tickets page shows a ticket: it stands where `show` says, and its key or title holds every word of
 * `query`, in any case and anywhere in a word, so `abc-1` finds ABC-101 and `csv exp` finds Export reports as CSV.
 */
export function ticketShown(
    ticket: Pick<TicketSummary, 'key' | 'title' | 'done' | 'awaiting' | 'running_run'>,
    show: TicketShow | undefined,
    query: string | undefined,
): boolean {
    return standsAt(ticket, show) && holdsEvery(`${ticket.key} ${ticket.title ?? ''}`, query)
}

type Standing = Pick<TicketSummary, 'done' | 'awaiting' | 'running_run'>

const STANDS_AT: Record<TicketShow, (ticket: Standing) => boolean> = {
    open: (ticket) => !ticket.done,
    working: (ticket) => ticket.running_run !== null,
    waiting: (ticket) => ticket.awaiting !== null,
    done: (ticket) => ticket.done,
}

function standsAt(ticket: Standing, show: TicketShow | undefined) {
    return show === undefined || STANDS_AT[show](ticket)
}

function holdsEvery(text: string, query: string | undefined) {
    const haystack = text.toLowerCase()
    const words = query?.toLowerCase().trim().split(/\s+/u) ?? []
    return words.every((word) => haystack.includes(word))
}
