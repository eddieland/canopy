// What a page holds that leaving it would lose: an edit not yet saved, or the operator's words in a form, not yet sent.
// Each says so with `usePending`, and a page that asks before it is left gives `PendingWork` what `usePendingWork`
// returns, which hears them.
import { createContext, useContext, useEffect, useState } from 'react'

/** What would be lost: an edit not yet saved, or words not yet sent. */
export type Pending = 'edit' | 'words'

/** Hears a part of the page say it holds work not yet saved or sent, by an id of its own, or that it no longer does. */
export type PendingReport = (id: symbol, pending: Pending | undefined) => void

/** What the parts under it report to: none by default, so a form on a page that does not ask says nothing. */
export const PendingWork = createContext<PendingReport | undefined>(undefined)

/** Says, while `pending`, that this part of the page holds `what` not yet saved or sent; and no longer once it goes. */
export function usePending(pending: boolean, what: Pending = 'words'): void {
    const report = useContext(PendingWork)
    const [id] = useState(() => Symbol('pending'))
    useEffect(() => {
        report?.(id, pending ? what : undefined)
        return () => report?.(id, undefined)
    }, [report, id, pending, what])
}

/** What the parts under a `PendingWork` hold, by their ids, and a stable report that keeps it, for `PendingWork`. */
export function usePendingWork(): [ReadonlyMap<symbol, Pending>, PendingReport] {
    const [held, setHeld] = useState<ReadonlyMap<symbol, Pending>>(new Map())
    const [report] = useState<PendingReport>(() => (id: symbol, pending: Pending | undefined) => {
        setHeld((before) => {
            if (before.get(id) === pending) {
                return before
            }
            const next = new Map(before)
            if (pending === undefined) {
                next.delete(id)
            } else {
                next.set(id, pending)
            }
            return next
        })
    })
    return [held, report]
}
