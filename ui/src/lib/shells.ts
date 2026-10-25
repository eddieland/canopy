import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * The Ghost's shells (drawn in src/components/ghost-shell.tsx), bought in Settings from the wallet Sprig's hats share
 * (src/lib/wallet.ts), as hats are. The Ghost always wears one: the Generalist Shell is free and owned from the start,
 * so a shell comes off only for another. What was bought, and the shell worn, are kept in localStorage like the theme,
 * and synced across tabs.
 */

/** A shell the Ghost can own. */
export type ShellId = 'generalist' | 'sprig' | 'pumpkin' | 'gilded' | 'vex'

/** One shell in the shop. */
export interface Shell {
    /** Which shell it is. */
    id: ShellId
    /** What the shop calls it. */
    name: string
    /** What it costs, in whole US dollars of lifetime spend: none for the shell the Ghost comes in. */
    price: number
    /** The shop's line about it. */
    blurb: string
}

/** The shell every Ghost comes in, owned from the start. */
export const FREE_SHELL: ShellId = 'generalist'

/** The shop, cheapest first, priced among the hats (`HATS` in src/lib/hats.ts). */
export const SHELLS: readonly Shell[] = [
    { id: 'generalist', name: 'Generalist Shell', price: 0, blurb: 'Standard issue. Every Ghost starts somewhere.' },
    { id: 'sprig', name: 'Sprig Shell', price: 100, blurb: 'Sprig, brought back by the Traveler. Still has notes.' },
    { id: 'pumpkin', name: 'Pumpkin Shell', price: 300, blurb: 'Festival of the Lost, all year. Nobody can stop you.' },
    { id: 'gilded', name: 'Gilded Shell', price: 1500, blurb: 'Every facet polished with Glimmer you did not have.' },
    { id: 'vex', name: 'Vex Shell', price: 5000, blurb: 'Its eye is red now. It says that is fine.' },
]

/** The shells owned, and the one worn. */
export interface Vault {
    /** The shells owned, in shop order: the free one always among them. */
    owned: ShellId[]
    /** The shell the Ghost wears, one of `owned`. */
    worn: ShellId
}

/** Where localStorage keeps the vault, as JSON. */
export const STORAGE_KEY = 'canopy-shells'
/** The vault before the first purchase: the free shell alone, worn. */
export const EMPTY: Vault = { owned: [FREE_SHELL], worn: FREE_SHELL }

/** The shell with this id. */
export function shellById(id: ShellId): Shell {
    const shell = SHELLS.find((s) => s.id === id)
    if (shell === undefined) {
        throw new Error(`no shell ${id}`)
    }
    return shell
}

/**
 * A vault from its stored JSON: the known shells among those owned, once each, with the free one, and the worn one
 * only if owned, else the free one.
 */
export function parseVault(raw: string | null): Vault {
    let stored: unknown = null
    try {
        stored = raw === null ? null : JSON.parse(raw)
    } catch {
        // Not JSON: an empty vault.
    }
    if (typeof stored !== 'object' || stored === null) {
        return EMPTY
    }
    const { owned, worn } = stored as Record<string, unknown>
    const listed = Array.isArray(owned) ? owned : []
    const kept = SHELLS.filter((s) => s.id === FREE_SHELL || listed.includes(s.id)).map((s) => s.id)
    return { owned: kept, worn: kept.find((id) => id === worn) ?? FREE_SHELL }
}

/** What every shell bought cost, in whole cents: what they took from the wallet. */
export function shellsCents(owned: readonly ShellId[]): number {
    return owned.reduce((sum, id) => sum + shellById(id).price * 100, 0)
}

/**
 * The vault once `id` is bought and worn, or undefined when it is owned already or `leftCents`, what is left in the
 * wallet (`balanceCents` in src/lib/wallet.ts), is short.
 */
export function buy(vault: Vault, id: ShellId, leftCents: number): Vault | undefined {
    if (vault.owned.includes(id) || leftCents < shellById(id).price * 100) {
        return undefined
    }
    const owned = SHELLS.filter((s) => s.id === id || vault.owned.includes(s.id)).map((s) => s.id)
    return { owned, worn: id }
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseVault, serialize: JSON.stringify })

/** The Ghost's vault. Re-renders on a change from this tab or another. */
export function useVault(): Vault {
    return useStoredSetting(setting)
}

/** Stores the vault and applies it now. */
export function setVault(next: Vault): void {
    setting.set(next)
}
