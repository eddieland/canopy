import { useSyncExternalStore } from 'react'

/** How the side rail shows: whole, or as a strip of the nav's icons. */
export type RailMode = 'full' | 'strip'

// Tailwind's `lg`. In a media query a rem is the browser's size, unscaled, as every breakpoint is.
const FULL = '(min-width: 64rem)'

/**
 * How the rail shows at the window's width: whole from `lg`, and under it a strip of the nav's icons. Narrower than
 * `lg` a whole rail leaves a list too little room in a narrow window.
 */
export function useRailMode(): RailMode {
    return useSyncExternalStore(subscribe, railMode)
}

function subscribe(listener: () => void): () => void {
    const query = globalThis.matchMedia(FULL)
    query.addEventListener('change', listener)
    return () => {
        query.removeEventListener('change', listener)
    }
}

function railMode(): RailMode {
    return globalThis.matchMedia(FULL).matches ? 'full' : 'strip'
}
