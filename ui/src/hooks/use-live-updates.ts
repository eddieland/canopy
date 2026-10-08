import { useQueryClient } from '@tanstack/react-query'

import { applyStreamEvent, parseStreamEvent } from '@/api/live'
import { keys } from '@/api/queries'
import { apiUrl } from '@/lib/base'

import { useEventStream, type StreamStatus } from './use-event-stream'

/**
 * Keeps the sessions and leases in the Query cache current from the server's event stream. Mount once, in the
 * shell. On a reconnect it refetches both, in the background: cached data stays on screen meanwhile.
 */
export function useLiveUpdates(): StreamStatus {
    const client = useQueryClient()
    return useEventStream(apiUrl('/events'), {
        parse: parseStreamEvent,
        onEvent: (event) => applyStreamEvent(client, event),
        onReconnect: () => {
            void client.invalidateQueries({ queryKey: keys.sessions })
            void client.invalidateQueries({ queryKey: keys.leases })
        },
    })
}
