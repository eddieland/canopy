import { useSyncExternalStore } from 'react'

/**
 * Which changes show a toast (src/hooks/use-live-updates.ts), by what they are about: for each subject, the states that
 * show one when something moves into them. Settings has a row of checkboxes for each subject. None shows one until
 * Settings turns it on. Kept in localStorage like the theme, as one JSON object keyed by subject, and synced across
 * tabs. A new subject is a key in `TOAST_STATES`, a line in `parseToastSettings`, and a row on Settings.
 */

/**
 * What a toast can be about, and the states of each that can show one, in the order Settings lists them. A ticket's
 * are its own phases (DESIGN §7), in the phase table's order, then done: the phases about a PR are a unit's, and the
 * tickets list the stream sends never carries them.
 */
export const TOAST_STATES = {
    tickets: ['ready', 'blocked', 'running', 'needs_human', 'human_replied', 'split', 'plan_proposed', 'done'],
} as const satisfies Record<string, readonly string[]>

/** What a toast can be about. */
export type ToastSubject = keyof typeof TOAST_STATES

/** A state of `S` that can show a toast. */
export type ToastState<S extends ToastSubject> = (typeof TOAST_STATES)[S][number]

/** The states turned on, for each subject, in `TOAST_STATES` order. */
export type ToastSettings = { [S in ToastSubject]: ToastState<S>[] }

/** Where localStorage keeps the settings, as JSON. */
export const STORAGE_KEY = 'canopy-toasts'
/** The settings until the operator changes them: no toasts. */
export const DEFAULTS: ToastSettings = { tickets: [] }

/** Settings from their stored JSON: each subject's known states, once each, in order; none for anything else. */
export function parseToastSettings(raw: string | null): ToastSettings {
    let stored: unknown = null
    try {
        stored = raw === null ? null : JSON.parse(raw)
    } catch {
        // Not JSON: the defaults.
    }
    if (typeof stored !== 'object' || stored === null) {
        return DEFAULTS
    }
    const { tickets } = stored as Record<string, unknown>
    return { tickets: known(TOAST_STATES.tickets, tickets) }
}

/** The settings once `state` of `subject` is turned on, or off when `on` is false. */
export function withState<S extends ToastSubject>(
    settings: ToastSettings,
    subject: S,
    state: ToastState<S>,
    on: boolean,
): ToastSettings {
    const shown: readonly string[] = settings[subject]
    const states: readonly ToastState<S>[] = TOAST_STATES[subject]
    return { ...settings, [subject]: states.filter((s) => (s === state ? on : shown.includes(s))) }
}

function known<T extends string>(states: readonly T[], value: unknown): T[] {
    return Array.isArray(value) ? states.filter((state) => value.includes(state)) : []
}

function read(): ToastSettings {
    try {
        return parseToastSettings(globalThis.localStorage.getItem(STORAGE_KEY))
    } catch {
        // Storage can be unavailable (privacy modes).
        return DEFAULTS
    }
}

let snapshot = read()
const listeners = new Set<() => void>()

function announce(next: ToastSettings): void {
    if (JSON.stringify(next) === JSON.stringify(snapshot)) {
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

function getSnapshot(): ToastSettings {
    return snapshot
}

/** Which changes show a toast. Re-renders on a change from this tab or another. */
export function useToastSettings(): ToastSettings {
    return useSyncExternalStore(subscribe, getSnapshot)
}

/** Stores which changes show a toast and applies it now. */
export function setToastSettings(next: ToastSettings): void {
    try {
        globalThis.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
        // Not persisted, but still applied for this page.
    }
    announce(next)
}
