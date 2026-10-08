import type { QueryClient } from '@tanstack/react-query'

import { api, unwrap } from './client'
import { keys } from './queries'
import type { Replied, Session, Started, Stopped } from './types'

/**
 * The operator's actions: sign in and out, and the CLI's verbs on a ticket. Each goes through the same function on the
 * server as `canopy start`, `stop`, and `reply`, with the same guards; a refusal is an ApiError naming its guard.
 */

export async function signIn(secret: string): Promise<Session> {
    return unwrap(await api.POST('/api/session', { body: { secret } }))
}

export async function signOut(): Promise<Session> {
    return unwrap(await api.DELETE('/api/session'))
}

export async function startTicket(key: string): Promise<Started> {
    return unwrap(await api.POST('/api/tickets/{key}/start', { params: { path: { key } } }))
}

export async function stopTicket(key: string, now: boolean): Promise<Stopped> {
    return unwrap(await api.POST('/api/tickets/{key}/stop', { params: { path: { key } }, body: { now } }))
}

export async function replyTicket(key: string, body: string, submission: string): Promise<Replied> {
    return unwrap(
        await api.POST('/api/tickets/{key}/replies', { params: { path: { key } }, body: { body, submission } }),
    )
}

/** After an action on a ticket: read it again now, rather than wait for the stream to say it changed. */
export function refreshTicket(client: QueryClient, key: string): Promise<void> {
    return client.invalidateQueries({ queryKey: keys.ticket(key) })
}

/** A submission id for a reply form, drawn when the form is rendered and kept until the reply is recorded. */
export function newSubmission(): string {
    return crypto.randomUUID()
}
