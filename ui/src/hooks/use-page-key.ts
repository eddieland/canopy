import { useEffect, useEffectEvent } from 'react'

import { pageKeyOf } from '@/lib/keys'
import type { PageKey } from '@/lib/keys'

/**
 * Answers one of the page keys (`src/lib/keys.ts`) while the caller is mounted: `onKey` runs on each press of it and
 * says whether it took the key, which then does nothing else. A key a caller does not take, such as one for a part of
 * the page that is hidden (the attention item behind its list at half width), is passed on to the next; one taken is
 * not, so two callers for the same key say apart when each takes it.
 */
export function usePageKey(key: PageKey, onKey: () => boolean): void {
    const take = useEffectEvent(onKey)
    useEffect(() => {
        function listener(event: KeyboardEvent) {
            if (event.defaultPrevented || pageKeyOf(event, event.target) !== key) {
                return
            }
            if (take()) {
                event.preventDefault()
            }
        }
        globalThis.addEventListener('keydown', listener)
        return () => globalThis.removeEventListener('keydown', listener)
    }, [key])
}

/** Whether an element is drawn: on the page and not inside anything hidden, so a key may move the focus to it. */
export function onScreen(element: Element | null): element is HTMLElement {
    return element instanceof HTMLElement && element.getClientRects().length > 0
}
