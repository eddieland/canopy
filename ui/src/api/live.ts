import type { QueryClient } from '@tanstack/react-query'

import { keys } from './queries'
import type { Run, StreamEvent } from './types'

/**
 * Writes one stream event into the Query cache. A list arrives whole and replaces the cached one; a changed ticket is
 * read again, only if a page shows it. The worktrees are not on the stream: a run starting or ending, or changing the
 * worktrees it holds, marks them stale, and they are read again only if a page shows them. Unknown event types are
 * ignored, so the server can add some.
 */
export function applyStreamEvent(client: QueryClient, event: StreamEvent): void {
    switch (event.type) {
        case 'attention.updated':
            client.setQueryData(keys.attention, event.items)
            break
        case 'runs.updated': {
            const before = client.getQueryData<Run[]>(keys.runs)
            client.setQueryData(keys.runs, event.runs)
            if (before !== undefined && holding(before) !== holding(event.runs)) {
                void client.invalidateQueries({ queryKey: keys.worktrees, refetchType: 'active' })
            }
            break
        }
        case 'tickets.updated':
            client.setQueryData(keys.tickets, event.tickets)
            break
        case 'ticket.changed':
            void client.invalidateQueries({ queryKey: keys.ticket(event.key), refetchType: 'active' })
            break
        case 'spend.updated':
            client.setQueryData(keys.spend, event.spend)
            break
        case 'tick.updated':
            client.setQueryData(keys.tick, { tick: event.tick })
            break
    }
}

/** Which running runs hold which worktrees, as one comparable string: a cost going up leaves it alone. */
export function holding(runs: Run[]): string {
    return runs
        .filter((r) => r.state === 'running')
        .map((r) => `${r.id}:${r.worktrees.join(',')}`)
        .toSorted()
        .join(' ')
}

const LISTS: Record<string, string> = {
    'attention.updated': 'items',
    'runs.updated': 'runs',
    'tickets.updated': 'tickets',
}

/** Parses an SSE `data` payload into a StreamEvent, or null when it is not one this UI knows. */
export function parseStreamEvent(data: string): StreamEvent | null {
    let value: unknown
    try {
        value = JSON.parse(data)
    } catch {
        return null
    }
    if (typeof value !== 'object' || value === null || !('type' in value)) return null
    const type = (value as { type: unknown }).type
    if (typeof type !== 'string') return null
    const list = LISTS[type]
    if (list !== undefined) {
        return Array.isArray((value as Record<string, unknown>)[list]) ? (value as StreamEvent) : null
    }
    if (type === 'ticket.changed' && typeof (value as { key?: unknown }).key === 'string') return value as StreamEvent
    if (type === 'tick.updated') {
        const tick = (value as { tick?: unknown }).tick
        return tick === null || (typeof tick === 'object' && tick !== undefined) ? (value as StreamEvent) : null
    }
    if (type === 'spend.updated') {
        const spend = (value as { spend?: unknown }).spend
        return typeof spend === 'object' && spend !== null ? (value as StreamEvent) : null
    }
    return null
}
