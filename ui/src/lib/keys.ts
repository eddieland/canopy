/**
 * The keys the pages answer to (ui/DESIGN.md, "Keys"): one letter each, with no modifier, typed anywhere but where it
 * would be text or a control's own key. `?` lists them, and the guide's overview says the same.
 */

/** What a page key asks for. */
export type PageKey = 'next' | 'previous' | 'reply' | 'find' | 'keys'

/** One line of the list `?` opens: the keys, as a keyboard prints them, and what they do. */
export interface KeyLine {
    /** The keys, each its own keycap. */
    keys: readonly string[]
    /** What they do, and where. */
    does: string
}

/**
 * Every key the pages answer to, in the order `?` lists them. The search box's `/` is its own (`isSearchShortcut`),
 * and the key that sends a reply is the reply form's, as Settings sets it; both are listed here so the list is whole.
 */
export const KEY_LINES: readonly KeyLine[] = [
    { keys: ['/'], does: 'Search the journal' },
    { keys: ['j', 'k'], does: 'The next or the previous item, on Attention; the arrows too, from a row' },
    { keys: ['r'], does: 'Write in the reply, or the note, on the page' },
    { keys: ['f'], does: 'Find lines in a transcript, in order or By call' },
    { keys: ['?'], does: 'This list' },
]

// Each key, by what it asks for.
const KEYS: Readonly<Record<string, PageKey>> = { j: 'next', k: 'previous', r: 'reply', f: 'find', '?': 'keys' }

// Where a key is the element's own: what takes text, and the widgets that read letters as they are typed (a menu's or
// a list box's typeahead), and every dialog, whose page behind it the key would change unseen.
const OWNS_KEYS = '[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]'

/**
 * What a key press asks of the page, or null: `j`, `k`, `r`, and `f` with no modifier, and `?` however it is typed,
 * from anywhere but a text field (`typing`) or a dialog or menu.
 */
export function pageKeyOf(
    event: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey' | 'isComposing'>,
    target: unknown,
): PageKey | null {
    const key = KEYS[event.key]
    if (key === undefined || event.ctrlKey || event.metaKey || event.altKey || event.isComposing) {
        return null
    }
    // `?` is Shift and `/` on most keyboards; a letter with Shift is a capital, which is not the key.
    if (key !== 'keys' && event.shiftKey) {
        return null
    }
    if (typing(target) || (target instanceof Element && target.closest(OWNS_KEYS) !== null)) {
        return null
    }
    return key
}

/** Whether a key press's target takes text: a field, a select, or an editable element, where a letter is a letter. */
export function typing(target: unknown): boolean {
    if (!(target instanceof HTMLElement)) {
        return false
    }
    return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

/**
 * The item `step` places away from `current` in `items`, held at either end, or the first item when none is current;
 * null when there is none to go to.
 */
export function stepped<T extends { id: string }>(
    items: readonly T[],
    current: string | undefined,
    step: 1 | -1,
): T | null {
    const at = items.findIndex((item) => item.id === current)
    if (at === -1) {
        return items[0] ?? null
    }
    const next = items[at + step]
    return next ?? null
}
