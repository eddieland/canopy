import { useMediaQuery } from '@/hooks/use-media-query'

/** How the side rail shows: whole, or as a strip of the nav's icons. */
export type RailMode = 'full' | 'strip'

// Tailwind's `lg`. In a media query a rem is the browser's size, unscaled, as every breakpoint is.
const FULL = '(min-width: 64rem)'

/**
 * How the rail shows at the window's width: whole from `lg`, and under it a strip of the nav's icons. Narrower than
 * `lg` a whole rail leaves a list too little room in a narrow window.
 */
export function useRailMode(): RailMode {
    return useMediaQuery(FULL) ? 'full' : 'strip'
}
