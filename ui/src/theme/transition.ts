import { flushSync } from 'react-dom'

import { getPalettes, setPalette } from './palette'
import type { Palette } from './palette'
import { getSnapshot, setPreference } from './store'
import type { ResolvedTheme, ThemePreference } from './store'

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'
const DURATION_MS = 420

/**
 * Switches to `preference` with a circular reveal growing from the center of `origin`.
 *
 * The new theme is applied inside document.startViewTransition, and flushSync makes React commit within the
 * callback, so the browser's "after" snapshot has both the new tokens and the re-rendered toggle. Swaps instantly
 * when the user prefers reduced motion or the browser has no View Transitions API.
 */
export function switchTheme(preference: ThemePreference, origin?: HTMLElement | null): void {
    void reveal(() => setPreference(preference), origin)
}

/**
 * Picks `palette` for `theme`, with the same reveal as a theme's when the page shows that theme, else at once; the
 * palette `theme` already wears changes nothing. Settles when the reveal is over: while it runs, the page under it
 * takes no pointer, so what follows the pointer, as the theme toggle's card does, waits for it.
 */
export async function switchPalette<T extends ResolvedTheme>(
    theme: T,
    palette: Palette<T>,
    origin?: HTMLElement | null,
): Promise<void> {
    if (getPalettes()[theme] === palette) {
        return
    }
    await reveal(() => setPalette(theme, palette), getSnapshot().resolved === theme ? origin : null)
}

/**
 * Runs `change` and lets React commit it, inside a view transition that grows from `origin` when there is one.
 * Settles when the transition is over, or at once without one.
 */
async function reveal(change: () => void, origin?: HTMLElement | null): Promise<void> {
    const commit = (): void => {
        flushSync(change)
    }
    if (
        typeof document.startViewTransition !== 'function' ||
        globalThis.matchMedia(REDUCED_MOTION).matches ||
        !origin
    ) {
        commit()
        return
    }

    const rect = origin.getBoundingClientRect()
    const x = rect.left + rect.width / 2
    const y = rect.top + rect.height / 2
    const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y))

    const transition = document.startViewTransition(commit)
    transition.ready
        .then(() =>
            document.documentElement.animate(
                { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
                {
                    duration: DURATION_MS,
                    easing: 'cubic-bezier(0.2, 0, 0, 1)',
                    pseudoElement: '::view-transition-new(root)',
                },
            ),
        )
        .catch(() => {
            // Skipped (another transition started, or the tab is hidden): the theme is already applied.
        })
    await transition.finished.catch(() => {
        // Skipped as above: it is over all the same.
    })
}
