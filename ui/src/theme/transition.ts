import { flushSync } from 'react-dom'

import { setPreference } from './store'
import type { ThemePreference } from './store'

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
    const commit = (): void => {
        flushSync(() => setPreference(preference))
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
}
