import { useSyncExternalStore } from 'react'

/** How the side rail shows: whole, as a strip of the nav's icons, or not at all, opened from the header. */
export type RailMode = 'full' | 'strip' | 'hidden'

// Tailwind's `lg` and `sm`. In a media query a rem is the browser's size, unscaled, as every breakpoint is.
const FULL = '(min-width: 64rem)'
const STRIP = '(min-width: 40rem)'

/**
 * How the rail shows at the window's width: whole from `lg`, a strip of the nav's icons from `sm`, and under it not
 * at all, the header's button opening it. Narrower than `lg` a whole rail leaves a list too little room: half of a
 * second monitor is under it.
 */
export function useRailMode(): RailMode {
    return useSyncExternalStore(subscribe, railMode)
}

function subscribe(listener: () => void): () => void {
    const queries = [FULL, STRIP].map((query) => globalThis.matchMedia(query))
    for (const query of queries) {
        query.addEventListener('change', listener)
    }
    return () => {
        for (const query of queries) {
            query.removeEventListener('change', listener)
        }
    }
}

function railMode(): RailMode {
    if (globalThis.matchMedia(FULL).matches) {
        return 'full'
    }
    return globalThis.matchMedia(STRIP).matches ? 'strip' : 'hidden'
}
