import { useSyncExternalStore } from 'react'

/**
 * Whether the page matches a CSS media query, such as `(min-width: 64rem)`. Re-renders when that changes: the window
 * resized past a breakpoint, or a system setting changed.
 */
export function useMediaQuery(query: string): boolean {
    const subscribe = (listener: () => void) => {
        const list = globalThis.matchMedia(query)
        list.addEventListener('change', listener)
        return () => {
            list.removeEventListener('change', listener)
        }
    }
    return useSyncExternalStore(subscribe, () => globalThis.matchMedia(query).matches)
}
