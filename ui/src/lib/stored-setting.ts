import { useSyncExternalStore } from 'react'

/**
 * A setting the operator chooses in this browser, kept in localStorage so it outlasts a reload, and synced across
 * tabs through the `storage` event. Each kind of setting (the send key, a list's order, Sprig's hats) makes one at
 * module level and keeps only what is its own: its key, how it reads what is stored, and what it does with it.
 */

/** How a setting is stored. */
export interface StoredSettingOptions<T> {
    /** Where localStorage keeps it. */
    key: string
    /** The value from what is stored, or from null when nothing is: a default for anything it does not recognize. */
    parse: (raw: string | null) => T
    /** The value as stored. Two values stored alike are the same setting, so a change to neither re-renders nothing. */
    serialize: (value: T) => string
}

/** A setting kept in localStorage, read in a component with `useStoredSetting` and outside one with `get`. */
export interface StoredSetting<T> {
    /** The setting now. */
    get: () => T
    /** Stores `next` and applies it now; where storage is unavailable, it still applies to this page. */
    set: (next: T) => void
    /**
     * Calls `listener` each time the setting changes, from this tab or another, as useSyncExternalStore does. Returns
     * the function that stops it.
     */
    subscribe: (listener: () => void) => () => void
}

/**
 * A setting kept under `key`. Read when this is called, and again when the first listener subscribes, since another
 * tab may have changed it between the two.
 */
export function storedSetting<T>({ key, parse, serialize }: StoredSettingOptions<T>): StoredSetting<T> {
    let snapshot = parse(readRaw(key))
    let stored = serialize(snapshot)
    const listeners = new Set<() => void>()

    const announce = (next: T) => {
        const raw = serialize(next)
        if (raw === stored) {
            return
        }
        stored = raw
        snapshot = next
        for (const listener of listeners) {
            listener()
        }
    }
    const onStorage = (event: StorageEvent) => {
        if (event.key === key || event.key === null) {
            announce(parse(readRaw(key)))
        }
    }
    const subscribe = (listener: () => void) => {
        listeners.add(listener)
        if (listeners.size === 1) {
            globalThis.addEventListener('storage', onStorage)
            announce(parse(readRaw(key)))
        }
        return () => {
            listeners.delete(listener)
            if (listeners.size === 0) {
                globalThis.removeEventListener('storage', onStorage)
            }
        }
    }
    const get = () => snapshot
    return {
        get,
        set: (next) => {
            try {
                globalThis.localStorage.setItem(key, serialize(next))
            } catch {
                // Not persisted, but still applied for this page.
            }
            announce(next)
        },
        subscribe,
    }
}

/** The setting, in a component. Re-renders on a change from this tab or another. */
export function useStoredSetting<T>(setting: StoredSetting<T>): T {
    return useSyncExternalStore(setting.subscribe, setting.get)
}

function readRaw(key: string): string | null {
    try {
        return globalThis.localStorage.getItem(key)
    } catch {
        // Storage can be unavailable (privacy modes).
        return null
    }
}
