import { useSyncExternalStore } from 'react'

/**
 * Sprig's hats (drawn in src/components/hat.tsx), bought in Settings with what canopy has spent over its whole life
 * (`total_usd` from `GET /api/spend`): every dollar the agent runtime reported is a dollar Sprig may spend on hats. The
 * wallet is that total less the price of every hat bought, so it fills as canopy works and never empties on its own.
 * What was bought, and the hat worn, are kept in localStorage like the theme, and synced across tabs. Nothing here
 * spends anything real: the total is only read.
 */

/** A hat Sprig can own. */
export type HatId = 'party' | 'beanie' | 'propeller' | 'top' | 'toque' | 'wizard' | 'crown' | 'halo'

/** One hat in the shop. */
export interface Hat {
    /** Which hat it is. */
    id: HatId
    /** What the shop calls it. */
    name: string
    /** What it costs, in whole US dollars of lifetime spend. */
    price: number
    /** The shop's line about it. */
    blurb: string
}

/**
 * The shop, cheapest first, priced for an operator who spends about $2,000 a month: a party hat inside a day, a top hat
 * in about two weeks, and the halo after about a year.
 */
export const HATS: readonly Hat[] = [
    { id: 'party', name: 'Party hat', price: 50, blurb: 'For the first fifty dollars. Every one of them was a party.' },
    { id: 'beanie', name: 'Beanie', price: 250, blurb: 'Keeps the wire warm through a long tick.' },
    { id: 'propeller', name: 'Propeller cap', price: 500, blurb: "Vibe coding's official headwear." },
    { id: 'top', name: 'Top hat', price: 1000, blurb: 'For reading diffs with a monocle.' },
    { id: 'toque', name: "Chef's toque", price: 2500, blurb: 'Let it cook.' },
    { id: 'wizard', name: 'Wizard hat', price: 5000, blurb: 'Any sufficiently advanced agent run is a hat.' },
    { id: 'crown', name: 'Crown', price: 10_000, blurb: 'Rules over three worktrees, benevolently.' },
    { id: 'halo', name: 'Halo', price: 25_000, blurb: 'You have given enough. Sprig thanks you.' },
]

/** The hats bought, and the one worn. */
export interface Wardrobe {
    /** The hats bought, in shop order. */
    owned: HatId[]
    /** The hat on Sprig's head, one of `owned`; null for none. */
    worn: HatId | null
}

/** Where localStorage keeps the wardrobe, as JSON. */
export const STORAGE_KEY = 'canopy-hats'
/** The wardrobe before the first purchase: empty, and a bare head. */
export const EMPTY: Wardrobe = { owned: [], worn: null }

/** The hat with this id. */
export function hatById(id: HatId): Hat {
    const hat = HATS.find((h) => h.id === id)
    if (hat === undefined) {
        throw new Error(`no hat ${id}`)
    }
    return hat
}

/** A wardrobe from its stored JSON: the known hats among those owned, once each, and the worn one only if owned. */
export function parseWardrobe(raw: string | null): Wardrobe {
    let stored: unknown = null
    try {
        stored = raw === null ? null : JSON.parse(raw)
    } catch {
        // Not JSON: an empty wardrobe.
    }
    if (typeof stored !== 'object' || stored === null) {
        return EMPTY
    }
    const { owned, worn } = stored as Record<string, unknown>
    const kept = Array.isArray(owned) ? HATS.filter((h) => owned.includes(h.id)).map((h) => h.id) : []
    return { owned: kept, worn: kept.find((id) => id === worn) ?? null }
}

/**
 * What is left to spend: the lifetime spend, in whole cents, less every hat bought. Never below zero, so a journal
 * started afresh shows an empty wallet rather than a debt. Nothing spent yet (`null`) is nothing to spend.
 */
export function balanceCents(totalUsd: number | null | undefined, owned: readonly HatId[]): number {
    const earned = Math.round((totalUsd ?? 0) * 100)
    const spent = owned.reduce((sum, id) => sum + hatById(id).price * 100, 0)
    return Math.max(0, earned - spent)
}

/** The wardrobe once `id` is bought and put on, or undefined when it is owned already or the wallet is short. */
export function buy(wardrobe: Wardrobe, id: HatId, totalUsd: number | null | undefined): Wardrobe | undefined {
    if (wardrobe.owned.includes(id) || balanceCents(totalUsd, wardrobe.owned) < hatById(id).price * 100) {
        return undefined
    }
    const owned = HATS.filter((h) => h.id === id || wardrobe.owned.includes(h.id)).map((h) => h.id)
    return { owned, worn: id }
}

function read(): Wardrobe {
    try {
        return parseWardrobe(globalThis.localStorage.getItem(STORAGE_KEY))
    } catch {
        // Storage can be unavailable (privacy modes).
        return EMPTY
    }
}

let snapshot = read()
const listeners = new Set<() => void>()

function announce(next: Wardrobe): void {
    if (next.worn === snapshot.worn && next.owned.join() === snapshot.owned.join()) {
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

function getSnapshot(): Wardrobe {
    return snapshot
}

/** Sprig's wardrobe. Re-renders on a change from this tab or another. */
export function useWardrobe(): Wardrobe {
    return useSyncExternalStore(subscribe, getSnapshot)
}

/** Stores the wardrobe and applies it now. */
export function setWardrobe(next: Wardrobe): void {
    try {
        globalThis.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
        // Not persisted, but still applied for this page.
    }
    announce(next)
}
