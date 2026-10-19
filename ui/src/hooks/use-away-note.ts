import { useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { useEffect, useEffectEvent } from 'react'

import { keys, runsSinceQuery } from '@/api/queries'
import type { AttentionItem } from '@/api/types'
import { useToast } from '@/hooks/use-toast'
import { AWAY_MS, awayChanges, awayLine } from '@/lib/away'

/**
 * How long, once the tab is shown again, the note waits for the attention list read after the return: the stream
 * starts over and sends it within a moment while the loop is up. Past this the loop is down, and the note is dropped
 * rather than told from the list the tab held before.
 */
export const FRESH_WAIT_MS = 30_000

/**
 * Shows a toast of what changed while the tab was hidden, when it was hidden at least `AWAY_MS` and something did
 * (`awayLine`): the attention items that are new and block work, those that cleared, the PRs opened, and the runs
 * ended. Mount once, in the shell, and only when signed in.
 */
export function useAwayNote(enabled: boolean): void {
    const client = useQueryClient()
    const toast = useToast()
    const show = useEffectEvent((line: string) => toast({ title: line, tone: 'note' }))

    useEffect(() => {
        if (!enabled) {
            return
        }
        let left: { at: number; attention: string[] } | null = null
        let cancel: (() => void) | null = null
        const onVisibility = () => {
            cancel?.()
            cancel = null
            if (document.visibilityState === 'hidden') {
                const items = client.getQueryData<AttentionItem[]>(keys.attention)
                left = items === undefined ? null : { at: Date.now(), attention: items.map((item) => item.id) }
                return
            }
            const away = left
            left = null
            if (away !== null && Date.now() - away.at >= AWAY_MS) {
                cancel = noteOnReturn(client, away, show)
            }
        }
        document.addEventListener('visibilitychange', onVisibility)
        return () => {
            document.removeEventListener('visibilitychange', onVisibility)
            cancel?.()
        }
    }, [enabled, client])
}

/**
 * Waits for the attention list read after now, counts the runs since the tab was hidden, and shows the line if any
 * changed. Returns what cancels it, as hiding the tab again does.
 */
function noteOnReturn(
    client: QueryClient,
    away: { at: number; attention: string[] },
    show: (line: string) => void,
): () => void {
    const returned = Date.now()
    const cancelled = new AbortController()
    // The list read at or after the return, or null once FRESH_WAIT_MS passes or the note is cancelled first.
    const fresh = new Promise<AttentionItem[] | null>((resolve) => {
        const unsubscribe = client.getQueryCache().subscribe(() => {
            const state = client.getQueryState<AttentionItem[]>(keys.attention)
            if (state?.data !== undefined && state.dataUpdatedAt >= returned) {
                settle(state.data)
            }
        })
        const timeout = setTimeout(() => settle(null), FRESH_WAIT_MS)
        cancelled.signal.addEventListener('abort', () => settle(null))
        function settle(items: AttentionItem[] | null) {
            unsubscribe()
            clearTimeout(timeout)
            resolve(items)
        }
    })
    void (async () => {
        const items = await fresh
        if (items === null) {
            return
        }
        const since = new Date(away.at).toISOString()
        const runs = await client.query(runsSinceQuery(since)).catch(() => null)
        if (runs === null || cancelled.signal.aborted) {
            return
        }
        const line = awayLine(since, new Date().toISOString(), awayChanges(away.attention, items, runs))
        if (line !== null) {
            show(line)
        }
    })()
    return () => cancelled.abort()
}
