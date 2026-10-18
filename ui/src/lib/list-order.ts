import { useSyncExternalStore } from 'react'

/**
 * Which way each list runs: oldest first or newest first. Every list in time has the order it reads in by default (a
 * conversation oldest first, as a chat does; ticks newest first, as the CLI prints them; tickets the most recently
 * updated first), and the operator can flip any one of them from its panel's header (`OrderToggle`). Each list keeps
 * its own choice, across reloads: kept in localStorage like the theme, and synced across tabs.
 */

/** Which end of a list comes first. */
export type Order = 'oldest' | 'newest'

/** Every list that can be flipped, and the order the server sends it in, which is its order until flipped. */
export const LISTS = {
    /** A ticket's conversation, on its page and in the attention page's item. */
    conversation: 'oldest',
    /** A chore's notes, on its page and in the attention page's item. */
    notes: 'oldest',
    /** A run's or tick's transcript, in the order the runtime printed it. */
    transcript: 'oldest',
    /** The runs page, a row per ticket by its latest run: running first, then the ones that ended last. */
    runs: 'newest',
    /** A ticket's recent runs. */
    'ticket-runs': 'newest',
    /** A ticket's decisions. */
    'ticket-decisions': 'newest',
    /** A chore's recent runs. */
    'chore-runs': 'newest',
    /** The ticks page. */
    ticks: 'newest',
    /** A tick's decisions, in the order its overseer made them. */
    'tick-decisions': 'oldest',
    /** The tickets page, by latest activity. */
    tickets: 'newest',
    /** The memory page's proposals, oldest first: the nearest to lapsing undecided. */
    'memory-proposals': 'oldest',
    /** The memory page's tickets with notes, the one whose newest note was written last first. */
    'memory-tickets': 'newest',
    /** The pull requests page, by latest activity. */
    'pull-requests': 'newest',
    /** The reviews page. */
    reviews: 'newest',
    /** A PR's runs, the ones that pushed to it. */
    'pr-runs': 'newest',
    /** A PR's reviews. */
    'pr-reviews': 'newest',
    /** A PR's decisions. */
    'pr-decisions': 'newest',
} as const satisfies Record<string, Order>

/** A list that can be flipped. */
export type ListName = keyof typeof LISTS

/**
 * The lists sorted by each row's latest activity, not by when it began: a ticket's or PR's last activity, each
 * ticket's latest run. Their newest end is the most recently updated, which may be the oldest row, so they say so.
 */
const BY_ACTIVITY: ReadonlySet<ListName> = new Set(['runs', 'tickets', 'pull-requests'])

/** Which end of `list` comes first in `order`, in words: `newest first`, or `recently updated` by activity. */
export function orderWords(list: ListName, order: Order): string {
    if (BY_ACTIVITY.has(list)) {
        return order === 'newest' ? 'recently updated' : 'least recently updated'
    }
    return `${order} first`
}

/** The orders the operator chose, by list. A list missing from it runs in its own order. */
export type Orders = Partial<Record<ListName, Order>>

/** Where localStorage keeps the chosen orders, as a JSON object from a list's name to its order. */
export const STORAGE_KEY = 'canopy-list-order'

/** The chosen orders as stored, keeping only lists and orders it knows: none for anything else. */
export function parseOrders(raw: string | null): Orders {
    let value: unknown
    try {
        value = JSON.parse(raw ?? '{}')
    } catch {
        return {}
    }
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
        return {}
    }
    const orders: Orders = {}
    for (const [name, order] of Object.entries(value as Record<string, unknown>)) {
        if (Object.hasOwn(LISTS, name) && (order === 'oldest' || order === 'newest')) {
            orders[name as ListName] = order
        }
    }
    return orders
}

/** The chosen orders with `list` set to `order`, as stored: a list back in its own order is left out. */
export function withOrder(orders: Orders, list: ListName, order: Order): string {
    const next: Orders = { ...orders }
    if (order === LISTS[list]) {
        delete next[list]
    } else {
        next[list] = order
    }
    return JSON.stringify(next, Object.keys(next).toSorted())
}

/** `items`, as the server sent them for `list`, in `order`: reversed when that is not the list's own. */
export function ordered<T>(list: ListName, order: Order, items: readonly T[]): T[] {
    return order === LISTS[list] ? [...items] : items.toReversed()
}

/** The order `list` runs in. Re-renders on a change from this tab or another. */
export function useListOrder(list: ListName): Order {
    return useSyncExternalStore(subscribe, getSnapshot)[list] ?? LISTS[list]
}

/** Sets the order `list` runs in, stores it, and applies it now. */
export function setListOrder(list: ListName, order: Order): void {
    const raw = withOrder(snapshot, list, order)
    try {
        globalThis.localStorage.setItem(STORAGE_KEY, raw)
    } catch {
        // Not persisted, but still applied for this page.
    }
    announce(raw)
}

function readRaw(): string | null {
    try {
        return globalThis.localStorage.getItem(STORAGE_KEY)
    } catch {
        // Storage can be unavailable (privacy modes).
        return null
    }
}

let stored = readRaw()
let snapshot = parseOrders(stored)
const listeners = new Set<() => void>()

function announce(raw: string | null): void {
    if (raw === stored) {
        return
    }
    stored = raw
    snapshot = parseOrders(raw)
    for (const listener of listeners) {
        listener()
    }
}

function onStorage(event: StorageEvent): void {
    if (event.key === STORAGE_KEY || event.key === null) {
        announce(readRaw())
    }
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    if (listeners.size === 1) {
        globalThis.addEventListener('storage', onStorage)
        announce(readRaw())
    }
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0) {
            globalThis.removeEventListener('storage', onStorage)
        }
    }
}

function getSnapshot(): Orders {
    return snapshot
}
