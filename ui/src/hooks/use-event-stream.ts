import { useEffect, useEffectEvent, useState } from 'react'

export type StreamStatus = 'connecting' | 'open' | 'reconnecting' | 'closed'

export interface EventStreamOptions<T> {
    /** Turns one message's `data` into a value, or null to drop it. */
    parse: (data: string) => T | null
    /** Called for each parsed message. May change between renders without reconnecting. */
    onEvent: (event: T) => void
    /** Called when the stream opens again after a drop: events may have been missed, so refetch what they feed. */
    onReconnect?: () => void
    enabled?: boolean
}

/**
 * Subscribes to a server-sent event stream for as long as the component is mounted. EventSource reconnects on its
 * own after a drop; this reports where it is, and tells the caller when it is back so it can catch up.
 *
 * For Query data, pair it with setQueryData in `onEvent` (see useLiveUpdates), never with polling.
 */
export function useEventStream<T>(url: string, options: EventStreamOptions<T>): StreamStatus {
    const { enabled = true } = options
    // Keyed by URL, so a new URL reads as 'connecting' without a state reset inside the effect.
    const [reported, setReported] = useState<{ url: string; status: StreamStatus } | null>(null)
    const onMessage = useEffectEvent((data: string) => {
        const event = options.parse(data)
        if (event !== null) options.onEvent(event)
    })
    const onReconnect = useEffectEvent(() => options.onReconnect?.())

    useEffect(() => {
        if (!enabled) return
        const source = new EventSource(url)
        let dropped = false
        source.addEventListener('open', () => {
            setReported({ url, status: 'open' })
            if (dropped) onReconnect()
            dropped = false
        })
        source.addEventListener('message', (message: MessageEvent<string>) => onMessage(message.data))
        source.addEventListener('error', () => {
            // CLOSED means the browser gave up (a non-2xx answer, such as the 501 before the API is wired).
            if (source.readyState === EventSource.CLOSED) {
                setReported({ url, status: 'closed' })
            } else {
                dropped = true
                setReported({ url, status: 'reconnecting' })
            }
        })
        return () => source.close()
    }, [url, enabled])

    if (!enabled) return 'closed'
    return reported?.url === url ? reported.status : 'connecting'
}
