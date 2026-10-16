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

const APPLE_NAMES: Partial<Record<string, string>> = { Mod: '⌘', Alt: '⌥', Shift: '⇧' }
const OTHER_NAMES: Partial<Record<string, string>> = { Mod: 'Ctrl' }

// The shortcut's modifiers and its key, the key upper-cased as a keyboard prints it.
function parts(keys: string): string[] {
    const all = keys.split('-')
    const key = all.pop() ?? ''
    return [...all, key.length === 1 ? key.toUpperCase() : key]
}
