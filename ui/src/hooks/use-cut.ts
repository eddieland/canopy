import { useState } from 'react'

/**
 * Whether the text in an element cut to fit (`truncate`) is cut, so what it leaves out can be offered whole. It is
 * measured when the returned ref is put on the element, which happens before the first paint, and again each time the
 * element's size or its text changes.
 */
export function useCut(): [(element: HTMLElement | null) => () => void, boolean] {
    const [cut, setCut] = useState(false)
    const ref = (element: HTMLElement | null) => {
        if (element === null) {
            return () => {}
        }
        const measure = () => setCut(element.scrollWidth > element.clientWidth)
        measure()
        const resized = new ResizeObserver(measure)
        resized.observe(element)
        const changed = new MutationObserver(measure)
        changed.observe(element, { subtree: true, childList: true, characterData: true })
        return () => {
            resized.disconnect()
            changed.disconnect()
        }
    }
    return [ref, cut]
}
