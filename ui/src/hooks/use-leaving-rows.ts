import { useEffect, useState } from 'react'

import { useMediaQuery } from '@/hooks/use-media-query'
import { settled, withLeaving } from '@/lib/leaving'
import type { Listed } from '@/lib/leaving'

// How long a cleared item's row plays its exit before it is let go: `animate-leave` in src/index.css, and a little
// over, so the row is folded shut before it goes.
const LEAVE_MS = 700

/** A list's rows as `useLeavingRows` keeps them, and where the list stands on its way to empty. */
export interface LeavingRows<T> {
    /** The rows to show: the items listed, and those that left, until they have played their exit. */
    rows: Listed<T>[]
    /** Whether the list is empty and its last rows are still playing their exit, which reduced motion does not show. */
    clearing: boolean
    /** Whether the page watched the list empty, rather than opening on it empty. */
    cleared: boolean
    /**
     * The id of the leaving row that may go off with a flash (a palette's starburst), if any: one at a time, and the
     * next not until the list has rested `LEAVE_MS` since, so a burst of clears is never a strobe. None under reduced
     * motion.
     */
    burst: string | undefined
}

/**
 * The list's rows as the stream changes it: an item that leaves keeps its row a moment, leaving, so it can go with a
 * small reward rather than vanish (ui/DESIGN.md, "Fun"). `data` is the list as the query holds it, compared once, by
 * identity, as it arrives, and `items` its items in the order shown. The leaving rows are let go together once the last
 * to leave has played its exit.
 */
export function useLeavingRows<T extends { id: string }>(
    data: unknown,
    items: readonly T[] | undefined,
): LeavingRows<T> {
    const still = useMediaQuery('(prefers-reduced-motion: reduce)')
    const [listed, setListed] = useState(() => ({
        from: data,
        rows: withLeaving<T>([], items ?? []),
        cleared: false,
        burst: undefined as string | undefined,
    }))
    if (listed.from !== data) {
        const rows = withLeaving(listed.rows, items ?? [])
        // The flash goes to the first row to leave while none is spent, and stays spent until the wait below frees it,
        // even if its item comes back, so two flashes are always at least `LEAVE_MS` apart.
        const burst = listed.burst ?? (still ? undefined : rows.find((row) => row.leaving)?.item.id)
        setListed({ from: data, rows, cleared: listed.cleared || (items?.length === 0 && rows.length > 0), burst })
    }
    // Which rows are leaving, so one more leaving starts the wait again and every exit plays in full.
    const leaving = listed.rows
        .filter((row) => row.leaving)
        .map((row) => row.item.id)
        .join(' ')
    const spent = listed.burst
    useEffect(() => {
        if (leaving === '' && spent === undefined) {
            return
        }
        const timer = globalThis.setTimeout(
            () => setListed((now) => ({ ...now, rows: settled(now.rows), burst: undefined })),
            LEAVE_MS,
        )
        return () => globalThis.clearTimeout(timer)
    }, [leaving, spent])
    return {
        rows: listed.rows,
        clearing: items?.length === 0 && listed.rows.length > 0 && !still,
        cleared: listed.cleared,
        burst: listed.burst,
    }
}
