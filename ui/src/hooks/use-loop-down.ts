import { createContext, useContext, useEffect, useState } from 'react'

import { RETRY_FIRST_MS } from './use-event-stream'
import type { StreamState } from './use-event-stream'

/**
 * How long the stream may be down before the header says so, in `status-blocked`, and how long the page has gone
 * unheard from: the first retry's wait, so a blip the browser recovers from on its own never reads as the loop down.
 */
export const OFFLINE_MS = RETRY_FIRST_MS
/** How long the stream may be down before the band over the page says the loop isn't answering, and how to start it. */
export const BAND_MS = 10_000

/** The shell's event stream, as useLiveUpdates reports it, for anything under the shell that reads it. */
export const StreamContext = createContext<StreamState>({ status: 'connecting', downSince: null })

/** Whether the loop that serves the page has stopped answering, as long as the stream has been down. */
export interface LoopDown {
    /** When the stream went down, in epoch milliseconds; null while it is up. */
    since: number | null
    /** Down for OFFLINE_MS or more: the page shows what the loop last said, and its actions wait for it. */
    offline: boolean
    /** Down for BAND_MS or more: the band over the page says so, and how to start the loop again. */
    band: boolean
}

/**
 * Where the loop stands as the stream says: up, just dropped, offline after OFFLINE_MS, and the band's after BAND_MS.
 * Only `canopy loop` serves the UI (D073), so a stream that will not come back almost always means the loop stopped.
 * It changes at each step on its own, with a timer from the drop, and back the moment the stream opens.
 */
export function useLoopDown(): LoopDown {
    const { downSince } = useContext(StreamContext)
    // The longest step reached since this drop, so a stale timer from an earlier drop never counts.
    const [reached, setReached] = useState<{ since: number; ms: number } | null>(null)
    useEffect(() => {
        if (downSince === null) {
            return
        }
        const timers = [OFFLINE_MS, BAND_MS].map((ms) =>
            globalThis.setTimeout(() => setReached({ since: downSince, ms }), Math.max(0, downSince + ms - Date.now())),
        )
        return () => {
            for (const timer of timers) {
                globalThis.clearTimeout(timer)
            }
        }
    }, [downSince])
    const ms = downSince !== null && reached?.since === downSince ? reached.ms : 0
    return { since: downSince, offline: ms >= OFFLINE_MS, band: ms >= BAND_MS }
}

/** Why an action that asks the loop waits while it is down: what the band says, short enough for a hover. */
export const LOOP_DOWN_TITLE = "The loop isn't answering: start it with `canopy loop` or `canopy daemon start`."
