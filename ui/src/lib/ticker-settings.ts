import { useSyncExternalStore } from 'react'

/**
 * The header ticker's settings (src/components/shell/ticker.tsx): how fast a headline crawls, and how many seconds
 * the window stays empty before the next one. Kept in localStorage like the theme, and synced across tabs.
 */

/** How fast a headline crawls, or `off` for no ticker. */
export type TickerSpeed = 'off' | 'slow' | 'normal' | 'spicy'

/** The ticker's settings as stored. */
export interface TickerSettings {
    /** How fast a headline crawls. */
    speed: TickerSpeed
    /** Seconds between one headline leaving and the next arriving. */
    gap: number
}

/** Where localStorage keeps the settings, as JSON. */
export const STORAGE_KEY = 'canopy-ticker'
/** The settings until the operator changes them: a normal crawl, and the next headline right after the last. */
export const DEFAULTS: TickerSettings = { speed: 'normal', gap: 0 }
/** The longest gap, in seconds: ten minutes. */
export const MAX_GAP = 600

/** How far a headline crawls each second, in rem, so it keeps its pace as the interface grows on a large screen. */
export const SPEED_REM: Record<Exclude<TickerSpeed, 'off'>, number> = { slow: 2.5, normal: 4.5, spicy: 9 }

const SPEEDS = new Set<string>(['off', 'slow', 'normal', 'spicy'])

function isSpeed(value: unknown): value is TickerSpeed {
    return typeof value === 'string' && SPEEDS.has(value)
}

/** A gap as stored: whole seconds from 0 to MAX_GAP, or undefined for anything that is not a number. */
export function clampGap(value: unknown): number | undefined {
    if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
    return Math.min(MAX_GAP, Math.max(0, Math.round(value)))
}

/** Settings from their stored JSON, each field falling back to its default when missing or invalid. */
export function parseSettings(raw: string | null): TickerSettings {
    let stored: unknown = null
    try {
        stored = raw === null ? null : JSON.parse(raw)
    } catch {
        // Not JSON: the defaults.
    }
    if (typeof stored !== 'object' || stored === null) return DEFAULTS
    const { speed, gap } = stored as Record<string, unknown>
    return { speed: isSpeed(speed) ? speed : DEFAULTS.speed, gap: clampGap(gap) ?? DEFAULTS.gap }
}

function read(): TickerSettings {
    try {
        return parseSettings(window.localStorage.getItem(STORAGE_KEY))
    } catch {
        // Storage can be unavailable (privacy modes).
        return DEFAULTS
    }
}

let snapshot = read()
const listeners = new Set<() => void>()

function announce(next: TickerSettings): void {
    if (next.speed === snapshot.speed && next.gap === snapshot.gap) return
    snapshot = next
    for (const listener of listeners) listener()
}

function onStorage(event: StorageEvent): void {
    if (event.key === STORAGE_KEY || event.key === null) announce(read())
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    if (listeners.size === 1) {
        window.addEventListener('storage', onStorage)
        announce(read())
    }
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0) window.removeEventListener('storage', onStorage)
    }
}

function getSnapshot(): TickerSettings {
    return snapshot
}

/** The ticker's settings. Re-renders on a change from this tab or another. */
export function useTickerSettings(): TickerSettings {
    return useSyncExternalStore(subscribe, getSnapshot)
}

/** Stores a change to one or both settings and applies it now. */
export function setTickerSettings(change: Partial<TickerSettings>): void {
    const next = { ...snapshot, ...change }
    try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
        // Not persisted, but still applied for this page.
    }
    announce(next)
}
