// Where the pointer last was, kept for the whole page from one listener, so anything may ask without a listener of
// its own: a hover card asks whether the pointer is on it as its link lets go.

/** A point of the window, in its own pixels. */
export interface Point {
    /** From the window's left edge. */
    x: number
    /** From the window's top edge. */
    y: number
}

const last: { at: Point | null } = { at: null }

if (typeof document !== 'undefined') {
    document.addEventListener(
        'pointermove',
        (event) => {
            last.at = { x: event.clientX, y: event.clientY }
        },
        { passive: true },
    )
    // Out of the window, where it is is not known.
    document.documentElement.addEventListener('pointerleave', () => {
        last.at = null
    })
}

/** Where the pointer last moved to, or null before its first move and once it has left the window. */
export function pointerAt(): Point | null {
    return last.at
}

/** Whether `point` is on `element`, or within `reach` pixels of it. Never, for no element or no point. */
export function isOver(element: Element | null, point: Point | null, reach = 0): boolean {
    if (element === null || point === null) {
        return false
    }
    const box = element.getBoundingClientRect()
    return (
        point.x >= box.left - reach &&
        point.x <= box.right + reach &&
        point.y >= box.top - reach &&
        point.y <= box.bottom + reach
    )
}
