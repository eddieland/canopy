/**
 * The theme preference: light, dark, or system. One store for the whole page, read with useTheme().
 *
 * The preference lives in localStorage, so it survives reloads, and a change in one tab reaches the others through
 * the `storage` event. The inline script in index.html applies it before first paint; this module keeps it applied
 * afterwards, including when the system theme changes while the preference is `system`.
 */

/** What the operator chose: a theme, or whatever the system uses. */
export type ThemePreference = 'light' | 'dark' | 'system'
/** The theme the page shows. */
export type ResolvedTheme = 'light' | 'dark'

/** The preference and the theme it resolves to, read together. */
export interface ThemeSnapshot {
    /** What the operator chose. */
    preference: ThemePreference
    /** What the page shows: the preference, or the system's theme for `system`. */
    resolved: ResolvedTheme
}

/** Shared with index.html's inline script. */
export const STORAGE_KEY = 'canopy-theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

function readPreference(): ThemePreference {
    try {
        const stored = window.localStorage.getItem(STORAGE_KEY)
        if (stored === 'light' || stored === 'dark') return stored
    } catch {
        // Storage can be unavailable (privacy modes); fall back to the system theme.
    }
    return 'system'
}

function systemTheme(): ResolvedTheme {
    return window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light'
}

function resolve(preference: ThemePreference): ResolvedTheme {
    return preference === 'system' ? systemTheme() : preference
}

/** Puts `snapshot` on <html>: the class Tailwind and the tokens key off, and color-scheme for form controls. */
function apply(snapshot: ThemeSnapshot): void {
    const root = document.documentElement
    root.classList.toggle('dark', snapshot.resolved === 'dark')
    root.style.colorScheme = snapshot.resolved
    root.dataset.theme = snapshot.preference
}

function take(): ThemeSnapshot {
    const preference = readPreference()
    return { preference, resolved: resolve(preference) }
}

let snapshot: ThemeSnapshot = take()
const listeners = new Set<() => void>()

function refresh(): void {
    const next = take()
    if (next.preference === snapshot.preference && next.resolved === snapshot.resolved) return
    snapshot = next
    apply(snapshot)
    for (const listener of listeners) listener()
}

function onStorage(event: StorageEvent): void {
    if (event.key === STORAGE_KEY || event.key === null) refresh()
}

/**
 * For useSyncExternalStore. Listens to other tabs and the system theme only while something is subscribed, and reads
 * both again on the first subscription: a change between the module loading and React subscribing has no listener.
 */
export function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    if (listeners.size === 1) {
        window.addEventListener('storage', onStorage)
        window.matchMedia(DARK_QUERY).addEventListener('change', refresh)
        refresh()
    }
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0) {
            window.removeEventListener('storage', onStorage)
            window.matchMedia(DARK_QUERY).removeEventListener('change', refresh)
        }
    }
}

/** For useSyncExternalStore: the current snapshot, the same object until the preference or the system theme changes. */
export function getSnapshot(): ThemeSnapshot {
    return snapshot
}

/** Stores `preference` and applies it now, synchronously, so a view transition can snapshot the result. */
export function setPreference(preference: ThemePreference): void {
    try {
        if (preference === 'system') window.localStorage.removeItem(STORAGE_KEY)
        else window.localStorage.setItem(STORAGE_KEY, preference)
    } catch {
        // Not persisted, but still applied for this page.
    }
    snapshot = { preference, resolved: resolve(preference) }
    apply(snapshot)
    for (const listener of listeners) listener()
}
