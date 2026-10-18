import type { TicketSummary } from '@/api/types'
import type { ToastState } from '@/lib/toast-settings'
import type { NewToast } from '@/lib/toasts'
import { readable } from '@/lib/words'

/**
 * A toast for each ticket in `after` that moved into a state of `on` since `before`: its phase changed to one, or it
 * was marked done. A ticket new to the list moved from no phase. Nothing before the first list, as the page has
 * nothing to compare it with.
 */
export function ticketToasts(
    before: readonly TicketSummary[] | undefined,
    after: readonly TicketSummary[],
    on: readonly ToastState<'tickets'>[],
): NewToast[] {
    if (before === undefined || on.length === 0) {
        return []
    }
    const was = new Map(before.map((ticket) => [ticket.key, ticket]))
    return after.flatMap((ticket) => {
        const prior = was.get(ticket.key)
        const entered = [
            ...(ticket.phase !== null && ticket.phase !== (prior?.phase ?? null) ? [ticket.phase] : []),
            ...(ticket.done && prior?.done !== true ? ['done'] : []),
        ]
        return entered
            .filter((state) => on.some((s) => s === state))
            .map((state): NewToast => {
                const toast: NewToast = { title: `${ticket.key}: ${readable(state)}`, tone: 'moved' }
                if (ticket.title !== null) {
                    toast.detail = ticket.title
                }
                return toast
            })
    })
}
