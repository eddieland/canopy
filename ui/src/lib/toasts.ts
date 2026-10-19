/** At most this many toasts show at once; a new one past it closes the oldest. */
export const MAX_TOASTS = 3

/** What a toast says: what an action did, and a line of what it did it to; or the note of what changed while away. */
export interface NewToast {
    /** What happened, in a few words: `Copied branch`. */
    title: string
    /** What it happened to, in monospace under the title, such as the text copied. */
    detail?: string
    /**
     * Whether the action did what it was asked (`done`, a check in the accent) or not (`failed`, a cross), or, with no
     * action behind it, what changed while the tab was hidden (`note`, a clock in the accent, shown longer).
     */
    tone: 'done' | 'failed' | 'note'
}

/** A toast in the stack: its id, unique among those shown, and whether it is still open or playing its way out. */
export interface ToastItem extends NewToast {
    /** Its key in the stack. */
    id: number
    /** False once it has closed; it stays in the list only until the next toast, so its exit can play. */
    open: boolean
}

/**
 * The stack with `toast` added last. Those already closed leave it, and past `MAX_TOASTS` open the oldest close. The
 * new id is past every id in the stack before it is pruned, so a toast still leaving never shares a key with it.
 */
export function addToast(toasts: readonly ToastItem[], toast: NewToast): ToastItem[] {
    const id = Math.max(0, ...toasts.map((t) => t.id)) + 1
    const open = toasts.filter((t) => t.open)
    const excess = open.length - (MAX_TOASTS - 1)
    return [...open.map((t, i) => (i < excess ? closed(t) : t)), { ...toast, id, open: true }]
}

/** The stack with the toast `id` closed, as its time running out, a swipe, or Escape does. */
export function closeToast(toasts: readonly ToastItem[], id: number): ToastItem[] {
    return toasts.map((t) => (t.id === id ? closed(t) : t))
}

function closed(toast: ToastItem): ToastItem {
    return { ...toast, open: false }
}
