import type { QueryClient } from '@tanstack/react-query'

import { keys } from './queries'
import type { Lease, Session, StreamEvent } from './types'

/** Replaces the item with `item.id`, or appends it. Returns a new array; the cache is never mutated in place. */
export function upsert<T extends { id: string }>(items: readonly T[] | undefined, item: T): T[] | undefined {
    // No list cached yet: leave it for the first fetch rather than invent a partial list.
    if (items === undefined) return undefined
    const index = items.findIndex((existing) => existing.id === item.id)
    if (index === -1) return [...items, item]
    return items.with(index, item)
}

/** Writes one stream event into the Query cache. Unknown event types are ignored, so the server can add some. */
export function applyStreamEvent(client: QueryClient, event: StreamEvent): void {
    switch (event.type) {
        case 'session.updated':
            client.setQueryData<Session[]>(keys.sessions, (old) => upsert(old, event.session))
            break
        case 'lease.updated':
            client.setQueryData<Lease[]>(keys.leases, (old) => upsert(old, event.lease))
            break
    }
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
    if (type === 'session.updated' && 'session' in value) return value as StreamEvent
    if (type === 'lease.updated' && 'lease' in value) return value as StreamEvent
    return null
}
