import { useSyncExternalStore } from 'react'

/**
 * Which key sends a reply or note (src/components/reply-form.tsx): Enter, as a chat does, with Shift+Enter for a new
 * line; Ctrl+Enter (⌘+Enter on a Mac), Enter making a new line; or neither, only the button. Kept in localStorage like
 * the theme, and synced across tabs.
 */

/** Which key sends: Enter, Ctrl+Enter (⌘+Enter on a Mac), or none, only the button. */
export type SendKey = 'enter' | 'mod-enter' | 'button'

/** Where localStorage keeps the setting. */
export const STORAGE_KEY = 'canopy-send-key'
/** The setting until the operator picks one: Enter, as a chat does. */
export const DEFAULT: SendKey = 'enter'

const SEND_KEYS = new Set<string>(['enter', 'mod-enter', 'button'])

/** The setting as stored, or the default for anything it does not recognize. */
export function parseSendKey(raw: string | null): SendKey {
    return raw !== null && SEND_KEYS.has(raw) ? (raw as SendKey) : DEFAULT
}

/** The parts of a key press that decide whether it sends. */
export interface KeyPress {
    /** The key's name, as `KeyboardEvent.key` gives it. */
    key: string
    /** Whether Shift was held. */
    shiftKey: boolean
    /** Whether Ctrl was held. */
    ctrlKey: boolean
    /** Whether ⌘ (or the Windows key) was held. */
    metaKey: boolean
    /** An Enter that ends an IME composition only commits it. */
    isComposing: boolean
}

/** Whether a key press in a reply or note sends it, under `setting`. */
export function sends(setting: SendKey, press: KeyPress): boolean {
    if (press.key !== 'Enter' || press.isComposing || press.shiftKey) {
        return false
    }
    if (setting === 'enter') {
        return true
    }
    if (setting === 'mod-enter') {
        return press.ctrlKey || press.metaKey
    }
    return false
}

/** Whether a browser's user agent names an Apple device, whose keyboard sends with ⌘ where others use Ctrl. */
export function isApple(userAgent: string): boolean {
    return /Mac|iPhone|iPad|iPod/u.test(userAgent)
}

/**
 * The keys that send under `setting`, in `aria-keyshortcuts` terms (`Control+Enter`), or undefined under `button`.
 * Both modifiers send, but the form names the one its keyboard has.
 */
export function sendShortcut(setting: SendKey, apple: boolean): string | undefined {
    if (setting === 'enter') {
        return 'Enter'
    }
    if (setting === 'mod-enter') {
        return apple ? 'Meta+Enter' : 'Control+Enter'
    }
    return undefined
}

function read(): SendKey {
    try {
        return parseSendKey(globalThis.localStorage.getItem(STORAGE_KEY))
    } catch {
        // Storage can be unavailable (privacy modes).
        return DEFAULT
    }
}

let snapshot = read()
const listeners = new Set<() => void>()

function announce(next: SendKey): void {
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

function getSnapshot(): SendKey {
    return snapshot
}

/** Which key sends. Re-renders on a change from this tab or another. */
export function useSendKey(): SendKey {
    return useSyncExternalStore(subscribe, getSnapshot)
}

/** Stores the setting and applies it now. */
export function setSendKey(next: SendKey): void {
    try {
        globalThis.localStorage.setItem(STORAGE_KEY, next)
    } catch {
        // Not persisted, but still applied for this page.
    }
    announce(next)
}
