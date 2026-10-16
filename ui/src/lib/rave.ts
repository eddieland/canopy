import { useSyncExternalStore } from 'react'

/**
 * The lightswitch rave, an Easter egg (src/components/shell/rave.tsx): flipped on by the light switch in the Settings
 * Fun panel's header, the lights go off and on over the whole app, with party beams sweeping through them, until the
 * switch is flipped back. Off until then. Kept in localStorage like the theme, so it outlasts a reload, and synced
 * across tabs, so every tab raves together.
 */

/** Whether the rave is on. */
export type RaveSetting = 'on' | 'off'

/** Where localStorage keeps the setting. */
export const STORAGE_KEY = 'canopy-rave'
/** The setting until the light switch is flipped: off. */
export const DEFAULT: RaveSetting = 'off'

/** The setting as stored, or the default for anything it does not recognize. */
export function parseRave(raw: string | null): RaveSetting {
    return raw === 'on' || raw === 'off' ? raw : DEFAULT
}

/** Whether the rave is on. Re-renders on a change from this tab or another. */
export function useRave(): RaveSetting {
    return useSyncExternalStore(subscribe, getSnapshot)
}

/** Stores the setting and applies it now. */
export function setRave(next: RaveSetting): void {
    try {
        globalThis.localStorage.setItem(STORAGE_KEY, next)
    } catch {
        // Not persisted, but still applied for this page.
    }
    announce(next)
}

function read(): RaveSetting {
    try {
        return parseRave(globalThis.localStorage.getItem(STORAGE_KEY))
    } catch {
        // Storage can be unavailable (privacy modes).
        return DEFAULT
    }
}

let snapshot = read()
const listeners = new Set<() => void>()

function announce(next: RaveSetting): void {
    if (next === snapshot) {
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

function getSnapshot(): RaveSetting {
    return snapshot
}
