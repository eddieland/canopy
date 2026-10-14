import { useQueryClient } from '@tanstack/react-query'

import { applyStreamEvent, parseStreamEvent } from '@/api/live'
import { keys } from '@/api/queries'
import { apiUrl } from '@/lib/base'

import { useEventStream } from './use-event-stream'
import type { StreamStatus } from './use-event-stream'

/**
 * Keeps the attention list, the runs, and the tickets in the Query cache current from the server's event stream. Mount
 * once, in the shell, and only when signed in: the stream needs a session. Every connection, a reconnect included,
 * starts with the three lists whole, so nothing needs refetching after a drop but the ticket a page shows, and the
 * server's meta: a drop is most often the loop restarting, perhaps upgraded, so it may serve a newer UI (NewerBuild).
 */
export function useLiveUpdates(enabled: boolean): StreamStatus {
    const client = useQueryClient()
    return useEventStream(apiUrl('/events'), {
        enabled,
        parse: parseStreamEvent,
        onEvent: (event) => applyStreamEvent(client, event),
        onReconnect: () => {
            void client.invalidateQueries({ queryKey: ['ticket'], refetchType: 'active' })
            void client.invalidateQueries({ queryKey: keys.meta })
        },
    })
}
