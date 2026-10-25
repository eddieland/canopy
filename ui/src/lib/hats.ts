import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * Sprig's hats (drawn in src/components/hat.tsx), bought in Settings from the wallet the Ghost's shells share
 * (src/lib/wallet.ts): what canopy has spent over its whole life, less everything bought. What was bought, and the hat
 * worn, are kept in localStorage like the theme, and synced across tabs.
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

/** What every hat bought cost, in whole cents: what they took from the wallet. */
export function hatsCents(owned: readonly HatId[]): number {
    return owned.reduce((sum, id) => sum + hatById(id).price * 100, 0)
}

/**
 * The wardrobe once `id` is bought and put on, or undefined when it is owned already or `leftCents`, what is left in
 * the wallet (`balanceCents` in src/lib/wallet.ts), is short.
 */
export function buy(wardrobe: Wardrobe, id: HatId, leftCents: number): Wardrobe | undefined {
    if (wardrobe.owned.includes(id) || leftCents < hatById(id).price * 100) {
        return undefined
    }
    const owned = HATS.filter((h) => h.id === id || wardrobe.owned.includes(h.id)).map((h) => h.id)
    return { owned, worn: id }
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseWardrobe, serialize: JSON.stringify })

/** Sprig's wardrobe. Re-renders on a change from this tab or another. */
export function useWardrobe(): Wardrobe {
    return useStoredSetting(setting)
}

/** Stores the wardrobe and applies it now. */
export function setWardrobe(next: Wardrobe): void {
    setting.set(next)
}
