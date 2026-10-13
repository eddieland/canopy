import { useSyncExternalStore } from 'react'

/**
 * Which ticks' output panels show their JSON pretty: each line of JSON laid out over several, indented. Each tick's
 * panel keeps its own choice, compact until the operator turns it on, across reloads: kept in localStorage like a
 * list's order, and synced across tabs. Only the latest `MAX_KEPT` ticks turned on are kept, so the key stays small.
 */

/** Where localStorage keeps the ticks whose output is pretty, as a JSON array of their ids, the latest last. */
export const STORAGE_KEY = 'canopy-pretty-output'

/** How many ticks' choices are kept: turning on one more drops the one turned on longest ago. */
export const MAX_KEPT = 200

/** The ids as stored, keeping only whole positive numbers: none for anything else. */
export function parsePretty(raw: string | null): number[] {
    let value: unknown
    try {
        value = JSON.parse(raw ?? '[]')
    } catch {
        return []
    }
    if (!Array.isArray(value)) return []
    return value.filter((id): id is number => Number.isSafeInteger(id) && id > 0)
}

/** The ids with `tick` turned on or off, as stored: on moves it to the end, and the oldest past `MAX_KEPT` go. */
export function withPretty(ids: readonly number[], tick: number, pretty: boolean): string {
    const rest = ids.filter((id) => id !== tick)
    return JSON.stringify(pretty ? [...rest, tick].slice(-MAX_KEPT) : rest)
}

/** Whether `tick`'s output panel shows its JSON pretty. Re-renders on a change from this tab or another. */
export function usePrettyOutput(tick: number): boolean {
    return useSyncExternalStore(subscribe, getSnapshot).includes(tick)
}

/** Turns `tick`'s pretty output on or off, stores it, and applies it now. */
export function setPrettyOutput(tick: number, pretty: boolean): void {
    const raw = withPretty(snapshot, tick, pretty)
    try {
        window.localStorage.setItem(STORAGE_KEY, raw)
    } catch {
        // Not persisted, but still applied for this page.
    }
    announce(raw)
}

function readRaw(): string | null {
    try {
        return window.localStorage.getItem(STORAGE_KEY)
    } catch {
        // Storage can be unavailable (privacy modes).
        return null
    }
}

let stored = readRaw()
let snapshot = parsePretty(stored)
const listeners = new Set<() => void>()

function announce(raw: string | null): void {
    if (raw === stored) return
    stored = raw
    snapshot = parsePretty(raw)
    for (const listener of listeners) listener()
}

function onStorage(event: StorageEvent): void {
    if (event.key === STORAGE_KEY || event.key === null) announce(readRaw())
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    if (listeners.size === 1) {
        window.addEventListener('storage', onStorage)
        announce(readRaw())
    }
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0) window.removeEventListener('storage', onStorage)
    }
}

function getSnapshot(): readonly number[] {
    return snapshot
}
