import { useState } from 'react'

/** What useMeasure watches, and when a new measure is no change. */
export interface MeasureOptions<T> {
    /** Also measure again when anything directly in the element changes size, not only the element itself. */
    children?: boolean
    /** Whether two measures are the same, so the second renders nothing. Defaults to `Object.is`. */
    same?: (before: T, after: T) => boolean
}

/**
 * Measures the element the returned ref is put on, with `measure`, and again each time it changes size: `initial`
 * until the first measure, which happens before the first paint. Returns the ref and the latest measure.
 */
export function useMeasure<T, E extends HTMLElement = HTMLElement>(
    measure: (element: E) => T,
    initial: T,
    { children = false, same = Object.is }: MeasureOptions<T> = {},
): [(element: E | null) => () => void, T] {
    const [value, setValue] = useState(initial)
    const ref = (element: E | null) => {
        if (element === null) {
            return () => {}
        }
        const observer = new ResizeObserver(() => {
            const next = measure(element)
            setValue((before) => (same(before, next) ? before : next))
        })
        observer.observe(element)
        if (children) {
            for (const child of element.children) {
                observer.observe(child)
            }
        }
        return () => observer.disconnect()
    }
    return [ref, value]
}
