import { useQueryClient } from '@tanstack/react-query'

import { applyStreamEvent, parseStreamEvent } from '@/api/live'
import { keys } from '@/api/queries'
import type { TicketSummary } from '@/api/types'
import { useToast } from '@/hooks/use-toast'
import { apiUrl } from '@/lib/base'
import { ticketToasts } from '@/lib/ticket-toasts'
import { useToastSettings } from '@/lib/toast-settings'

import { useEventStream } from './use-event-stream'
import type { StreamState } from './use-event-stream'

/**
 * Keeps the attention list, the runs, and the tickets in the Query cache current from the server's event stream. Mount
 * once, in the shell, and only when signed in: the stream needs a session. Every connection, a reconnect included,
 * starts with the three lists whole, so nothing needs refetching after a drop but the ticket a page shows, and the
 * server's meta: a drop is most often the loop restarting, perhaps upgraded, so it may serve a newer UI (NewerBuild).
 * A change Settings turned toasts on for shows one: a ticket in the tickets list moving into a state (`ticketToasts`).
 */
export function useLiveUpdates(enabled: boolean): StreamState {
    const client = useQueryClient()
    const show = useToast()
    const toasts = useToastSettings()
    return useEventStream(apiUrl('/events'), {
        enabled,
        parse: parseStreamEvent,
        onEvent: (event) => {
            const before = client.getQueryData<TicketSummary[]>(keys.tickets)
            applyStreamEvent(client, event)
            if (event.type === 'tickets.updated') {
                for (const toast of ticketToasts(before, event.tickets, toasts.tickets)) {
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
