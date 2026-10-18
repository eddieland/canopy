import { addTransitionType, startTransition } from 'react'

/** The type of a transition that redraws part of a page, not the page, which the outlet does not cross-fade. */
export const IN_PAGE = 'in-page'

/**
 * Runs `update` in a transition that redraws part of the page, as a search redraws the rows it keeps: React renders it
 * behind what the operator does, as `useDeferredValue` would, and the `<ViewTransition>` around the outlet leaves it
 * be (`AppShell`). Untyped, every transition inside the outlet cross-fades the whole page, so each key typed in a
 * search waited on a snapshot of all of it.
 */
export function inPage(update: () => void): void {
    startTransition(() => {
        addTransitionType(IN_PAGE)
        update()
    })
}
