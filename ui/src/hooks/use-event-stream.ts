import { useEffect, useEffectEvent, useState } from 'react'

/** Where a stream is: opening, open, reconnecting after a drop or a refusal, or closed because it is disabled. */
export type StreamStatus = 'connecting' | 'open' | 'reconnecting' | 'closed'

/**
 * How long a stream may be down before useEventStream starts it over, doubling on each try up to RETRY_MAX_MS. A
 * browser retries on its own within a few seconds, but gives up for good on a refusal (a proxy's 502 while the loop
 * restarts), and iOS Safari, after the page was in the background, often stops retrying without saying so.
 */
export const RETRY_FIRST_MS = 5_000
/** The longest wait between two starts of a stream that stays down. */
export const RETRY_MAX_MS = 60_000
/** A page hidden this long may hold a stream the system cut without telling it, as iOS does: shown, it starts over. */
export const HIDDEN_MS = 30_000

/** What useEventStream does with the stream's messages. */
export interface EventStreamOptions<T> {
    /** Turns one message's `data` into a value, or null to drop it. */
    parse: (data: string) => T | null
    /** Called for each parsed message. May change between renders without reconnecting. */
    onEvent: (event: T) => void
    /** Called when the stream opens again after a drop: events may have been missed, so refetch what they feed. */
    onReconnect?: () => void
    /** Whether to connect at all. Off closes the stream. Defaults to on. */
    enabled?: boolean
}

/**
 * Subscribes to a server-sent event stream for as long as the component is mounted, reports where it is, and tells the
 * caller when it is back after a drop so it can catch up. EventSource reconnects on its own; when it has not within
 * RETRY_FIRST_MS, this closes it and opens a new one, and it opens a new one at once when the device is back online,
 * or when the page is shown again after HIDDEN_MS or with the stream down.
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
        let source: EventSource | null = null
        let dropped = false
        let retry: ReturnType<typeof setTimeout> | null = null
        let delay = RETRY_FIRST_MS
        let hiddenAt: number | null = null

        const stopRetry = () => {
            if (retry !== null) clearTimeout(retry)
            retry = null
        }
        const connect = () => {
            stopRetry()
            source?.close()
            const current = new EventSource(url)
            source = current
            current.addEventListener('open', () => {
                stopRetry()
                delay = RETRY_FIRST_MS
                setReported({ url, status: 'open' })
                if (dropped) onReconnect()
                dropped = false
            })
            current.addEventListener('message', (message: MessageEvent<string>) => onMessage(message.data))
            current.addEventListener('error', () => {
                dropped = true
                setReported({ url, status: 'reconnecting' })
                // One timer per drop: the browser's own retries fire `error` again while it waits.
                if (retry !== null) return
                retry = setTimeout(connect, delay)
                delay = Math.min(delay * 2, RETRY_MAX_MS)
            })
        }
        const startOver = () => {
            dropped = true
            delay = RETRY_FIRST_MS
            setReported({ url, status: 'reconnecting' })
            connect()
        }
        const onVisibility = () => {
            if (document.visibilityState === 'hidden') {
                hiddenAt = Date.now()
                return
            }
            const away = hiddenAt === null ? 0 : Date.now() - hiddenAt
            hiddenAt = null
            if (away >= HIDDEN_MS || source?.readyState !== EventSource.OPEN) startOver()
        }
        const onOnline = () => {
            if (source?.readyState !== EventSource.OPEN) startOver()
        }
        // A page restored from the back-forward cache had its stream closed when it was put there.
        const onPageShow = (event: PageTransitionEvent) => {
            if (event.persisted) startOver()
        }

        connect()
        document.addEventListener('visibilitychange', onVisibility)
        window.addEventListener('online', onOnline)
        window.addEventListener('pageshow', onPageShow)
        return () => {
            stopRetry()
            source?.close()
            document.removeEventListener('visibilitychange', onVisibility)
            window.removeEventListener('online', onOnline)
            window.removeEventListener('pageshow', onPageShow)
        }
    }, [url, enabled])

    if (!enabled) return 'closed'
    return reported?.url === url ? reported.status : 'connecting'
}
