import { useQueryClient } from '@tanstack/react-query'

import { applyStreamEvent, parseStreamEvent } from '@/api/live'
import { keys } from '@/api/queries'
import type { TicketSummary } from '@/api/types'
import { useToast } from '@/hooks/use-toast'
import { apiUrl } from '@/lib/base'
import { ticketToasts, useTicketToasts } from '@/lib/ticket-toasts'

import { useEventStream } from './use-event-stream'
import type { StreamState } from './use-event-stream'

/**
 * Keeps the attention list, the runs, and the tickets in the Query cache current from the server's event stream. Mount
 * once, in the shell, and only when signed in: the stream needs a session. Every connection, a reconnect included,
 * starts with the three lists whole, so nothing needs refetching after a drop but the ticket a page shows, and the
 * server's meta: a drop is most often the loop restarting, perhaps upgraded, so it may serve a newer UI (NewerBuild).
 * A ticket the tickets list shows moving into a state Settings turned on shows a toast (`ticketToasts`).
 */
export function useLiveUpdates(enabled: boolean): StreamState {
    const client = useQueryClient()
    const show = useToast()
    const states = useTicketToasts()
    return useEventStream(apiUrl('/events'), {
        enabled,
        parse: parseStreamEvent,
        onEvent: (event) => {
            const before = client.getQueryData<TicketSummary[]>(keys.tickets)
            applyStreamEvent(client, event)
            if (event.type === 'tickets.updated') {
                for (const toast of ticketToasts(before, event.tickets, states)) {
                    show(toast)
                }
            }
        },
        onReconnect: () => {
            void client.invalidateQueries({ queryKey: ['ticket'], refetchType: 'active' })
            void client.invalidateQueries({ queryKey: keys.meta })
        },
    })
}
