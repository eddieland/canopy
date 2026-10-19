import { useQueryClient } from '@tanstack/react-query'

import { applyStreamEvent, parseStreamEvent } from '@/api/live'
import { keys } from '@/api/queries'
import type { ReviewSummary, StreamEvent, TicketSummary } from '@/api/types'
import { useToast } from '@/hooks/use-toast'
import { apiUrl } from '@/lib/base'
import { reviewToasts } from '@/lib/review-toasts'
import { ticketToasts } from '@/lib/ticket-toasts'
import { useToastSettings } from '@/lib/toast-settings'
import type { ToastSettings } from '@/lib/toast-settings'
import type { NewToast } from '@/lib/toasts'

import { useEventStream } from './use-event-stream'
import type { StreamState } from './use-event-stream'

/**
 * Keeps the attention list, the runs, and the tickets in the Query cache current from the server's event stream. Mount
 * once, in the shell, and only when signed in: the stream needs a session. Every connection, a reconnect included,
 * starts with the three lists whole, so nothing needs refetching after a drop but the ticket a page shows, and the
 * server's meta: a drop is most often the loop restarting, perhaps upgraded, so it may serve a newer UI (NewerBuild).
 * A change Settings turned toasts on for shows one: a ticket moving into a state (`ticketToasts`), or a review
 * starting or ending (`reviewToasts`), each against the list the cache held before the event.
 */
export function useLiveUpdates(enabled: boolean): StreamState {
    const client = useQueryClient()
    const show = useToast()
    const toasts = useToastSettings()
    return useEventStream(apiUrl('/events'), {
        enabled,
        parse: parseStreamEvent,
        onEvent: (event) => {
            const before: Before = {
                tickets: client.getQueryData<TicketSummary[]>(keys.tickets),
                reviews: client.getQueryData<ReviewSummary[]>(keys.reviews),
            }
            applyStreamEvent(client, event)
            for (const toast of changeToasts(before, event, toasts)) {
                show(toast)
            }
        },
        onReconnect: () => {
            void client.invalidateQueries({ queryKey: ['ticket'], refetchType: 'active' })
            void client.invalidateQueries({ queryKey: keys.meta })
        },
    })
}

// Each list a toast compares, as the cache held it before an event: undefined before its first.
interface Before {
    tickets: TicketSummary[] | undefined
    reviews: ReviewSummary[] | undefined
}

// The toasts an event's list asks for, against the list before it.
function changeToasts(before: Before, event: StreamEvent, toasts: ToastSettings): NewToast[] {
    if (event.type === 'tickets.updated') {
        return ticketToasts(before.tickets, event.tickets, toasts.tickets)
    }
    if (event.type === 'reviews.updated') {
        return reviewToasts(before.reviews, event.reviews, toasts.reviews)
    }
    return []
}
