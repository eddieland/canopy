import { useSyncExternalStore } from 'react'

import type { TicketSummary } from '@/api/types'
import type { NewToast } from '@/lib/toasts'
import { readable } from '@/lib/words'

/**
 * Which of a ticket's states show a toast when a ticket moves into one (src/hooks/use-live-updates.ts): each of the
 * ticket's own phases (DESIGN §7), and done. The phases about a PR are a unit's, not the ticket's, so the tickets list
 * the stream sends never carries them. None shows one until Settings turns it on. Kept in localStorage like the theme,
 * and synced across tabs.
 */

/** The states a toast can announce, in the phase table's order, then done. */
export const TICKET_TOAST_STATES = [
    'ready',
    'blocked',
    'running',
    'needs_human',
    'human_replied',
    'split',
    'plan_proposed',
    'done',
] as const

/** One of `TICKET_TOAST_STATES`. */
export type TicketToastState = (typeof TICKET_TOAST_STATES)[number]

/** Where localStorage keeps the states turned on, as JSON. */
export const STORAGE_KEY = 'canopy-ticket-toasts'

/** States as stored: the known ones among `value`, once each, in `TICKET_TOAST_STATES` order; none for a non-list. */
export function parseStates(raw: string | null): TicketToastState[] {
    let value: unknown = null
    try {
        value = raw === null ? null : JSON.parse(raw)
    } catch {
        // Not JSON: none.
    }
    if (!Array.isArray(value)) {
        return []
    }
    return TICKET_TOAST_STATES.filter((state) => value.includes(state))
}

/** The states turned on once `state` is turned on, or off when `on` is false. */
export function withState(states: readonly TicketToastState[], state: TicketToastState, on: boolean) {
    return TICKET_TOAST_STATES.filter((s) => (s === state ? on : states.includes(s)))
}

/**
 * A toast for each ticket in `after` that moved into a state of `on` since `before`: its phase changed to one, or it
 * was marked done. A ticket new to the list moved from no phase. Nothing before the first list, as the page has
 * nothing to compare it with.
 */
export function ticketToasts(
    before: readonly TicketSummary[] | undefined,
    after: readonly TicketSummary[],
    on: readonly TicketToastState[],
): NewToast[] {
    if (before === undefined || on.length === 0) {
        return []
    }
    const was = new Map(before.map((ticket) => [ticket.key, ticket]))
    return after.flatMap((ticket) => {
        const prior = was.get(ticket.key)
        const entered = [
            ...(ticket.phase !== null && ticket.phase !== (prior?.phase ?? null) ? [ticket.phase] : []),
            ...(ticket.done && prior?.done !== true ? ['done'] : []),
        ]
        return entered
            .filter((state) => on.some((s) => s === state))
            .map((state): NewToast => {
                const toast: NewToast = { title: `${ticket.key}: ${readable(state)}`, tone: 'moved' }
                if (ticket.title !== null) {
                    toast.detail = ticket.title
                }
                return toast
            })
    })
}

function read(): TicketToastState[] {
    try {
        return parseStates(globalThis.localStorage.getItem(STORAGE_KEY))
    } catch {
        // Storage can be unavailable (privacy modes).
        return []
    }
}

let snapshot = read()
const listeners = new Set<() => void>()

function announce(next: TicketToastState[]): void {
    if (next.join() === snapshot.join()) {
        return
    }
    snapshot = next
    for (const listener of listeners) {
        listener()
    }
}

function onStorage(event: StorageEvent): void {
    if (event.key === STORAGE_KEY || event.key === null) {
        announce(read())
    }
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    if (listeners.size === 1) {
        globalThis.addEventListener('storage', onStorage)
        announce(read())
    }
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0) {
            globalThis.removeEventListener('storage', onStorage)
        }
    }
}

function getSnapshot(): TicketToastState[] {
    return snapshot
}

/** The states that show a toast. Re-renders on a change from this tab or another. */
export function useTicketToasts(): TicketToastState[] {
    return useSyncExternalStore(subscribe, getSnapshot)
}

/** Stores the states that show a toast and applies them now. */
export function setTicketToasts(next: TicketToastState[]): void {
    try {
        globalThis.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
        // Not persisted, but still applied for this page.
    }
    announce(next)
}
