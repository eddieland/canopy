import type { KeyboardEvent } from 'react'

import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * Which key sends what the operator writes to send, in every such field (`useSendKeys`): Enter, as a chat does, with
 * Shift+Enter for a new line; Ctrl+Enter (⌘+Enter on a Mac), Enter making a new line; or neither, only the button.
 * Kept in localStorage like the theme, and synced across tabs.
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

const setting = storedSetting({ key: STORAGE_KEY, parse: parseSendKey, serialize: (value: SendKey) => value })

/** Which key sends. Re-renders on a change from this tab or another. */
export function useSendKey(): SendKey {
    return useStoredSetting(setting)
}

/** Stores the setting and applies it now. */
export function setSendKey(next: SendKey): void {
    setting.set(next)
}

const APPLE = isApple(navigator.userAgent)

/** A field's send key, as Settings names it, and what its send button says of it. */
export interface SendKeys {
    /**
     * Submits the form the field is in when a key press is the one that sends, as its send button would; any other
     * Enter makes a new line.
     */
    onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void
    /** The keys that send, for the send button's `aria-keyshortcuts` and `SendKeycap`; undefined under Button only. */
    shortcut: string | undefined
}

/**
 * The send key for any field the operator writes in and sends, so every one sends on the same key. Re-renders on a
 * change of the setting, from this tab or another. A form it submits checks it may send, as its disabled button does.
 */
export function useSendKeys(): SendKeys {
    const sendKey = useSendKey()
    return {
        onKeyDown: (event) => {
            const { key, shiftKey, ctrlKey, metaKey } = event
            if (sends(sendKey, { key, shiftKey, ctrlKey, metaKey, isComposing: event.nativeEvent.isComposing })) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
            }
        },
        shortcut: sendShortcut(sendKey, APPLE),
    }
}
