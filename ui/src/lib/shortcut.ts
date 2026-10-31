/**
 * A keyboard shortcut, written as the plan editor binds it (Tiptap's `Mod-Alt-m`, `Mod` being ⌘ on an Apple keyboard
 * and Ctrl elsewhere), named for a person and for a screen reader. The toolbar shows each control's shortcut on hover
 * and declares it with `aria-keyshortcuts`, so the keys the editor already takes can be found without a manual.
 */

/** The shortcut as a person reads it on this keyboard: `⌘⌥M` on an Apple one, `Ctrl+Alt+M` elsewhere. */
export function keysLabel(keys: string, apple: boolean): string {
    const names = parts(keys).map((part) => (apple ? (APPLE_NAMES[part] ?? part) : (OTHER_NAMES[part] ?? part)))
    return apple ? names.join('') : names.join('+')
}

/** The shortcut in `aria-keyshortcuts` terms: `Meta+Alt+M` on an Apple keyboard, `Control+Alt+M` elsewhere. */
export function ariaKeys(keys: string, apple: boolean): string {
    return parts(keys)
        .map((part) => (part === 'Mod' ? (apple ? 'Meta' : 'Control') : part))
        .join('+')
}

/**
 * Whether a key press is the shortcut on this keyboard: its key, with its modifiers and no others, `Mod` being ⌘ on an
 * Apple keyboard and Ctrl elsewhere.
 */
export function isPressed(
    keys: string,
    press: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey'>,
    apple: boolean,
): boolean {
    const modifiers = keys.split('-')
    const key = modifiers.pop() ?? ''
    const mod = modifiers.includes('Mod')
    return (
        press.key.toLowerCase() === key.toLowerCase() &&
        press.metaKey === (apple && mod) &&
        press.ctrlKey === (!apple && mod) &&
        press.altKey === modifiers.includes('Alt') &&
        press.shiftKey === modifiers.includes('Shift')
    )
}

/**
 * Whether a key press or a paste lands in a text field, or in the plan editor, which is editable: where a key the shell
 * listens for anywhere else (`/`, `R`, 2048) is just a character someone is typing.
 */
export function isTextField(target: unknown): boolean {
    return (
        target instanceof HTMLElement &&
        (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
    )
}

/**
 * Whether a key press is `letter` alone, pressed rather than held, in either case (Caps Lock types it upper case with
 * no Shift), and not taken already: the keys the shell's dialogs open on, `R` and `T`.
 */
export function isBareKey(letter: string, event: KeyboardEvent): boolean {
    return (
        event.key.toLowerCase() === letter.toLowerCase() &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        !event.shiftKey &&
        !event.repeat &&
        !event.defaultPrevented
    )
}

/** Whether a dialog is open already, as the jump palette, 2048, or the rail's sheet each is: one at a time. */
export function dialogOpen(): boolean {
    return document.querySelector('[role="dialog"], [role="alertdialog"]') !== null
}

const APPLE_NAMES: Partial<Record<string, string>> = { Mod: '⌘', Alt: '⌥', Shift: '⇧' }
const OTHER_NAMES: Partial<Record<string, string>> = { Mod: 'Ctrl' }

// The shortcut's modifiers and its key, the key upper-cased as a keyboard prints it.
function parts(keys: string): string[] {
    const all = keys.split('-')
    const key = all.pop() ?? ''
    return [...all, key.length === 1 ? key.toUpperCase() : key]
}
