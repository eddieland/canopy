import type { QueryClient } from '@tanstack/react-query'

import { api, unwrap } from './client'
import { keys } from './queries'
import type { ConfigReload, Forgot, LoopState, PauseChanged, Replied, Session, Started, Stopped } from './types'

/**
 * The operator's actions: sign in and out, the CLI's verbs on a ticket, a note to a chore, and pausing the loop. Each
 * goes through the same function on the server as `canopy start`, `stop`, `reply`, `forget`, `pause`, and `resume`,
 * with the same guards; a refusal is an ApiError naming its guard.
 */

/** Signs this browser in with the listener secret. The secret is sent here once and never kept in the page. */
export async function signIn(secret: string): Promise<Session> {
    return unwrap(await api.POST('/api/session', { body: { secret } }))
}

/** Signs this browser out: the server drops its session cookie. */
export async function signOut(): Promise<Session> {
    return unwrap(await api.DELETE('/api/session'))
}

/** `canopy start`: the ticket is started privately, and the next tick picks it up. */
export async function startTicket(key: string): Promise<Started> {
    return unwrap(await api.POST('/api/tickets/{key}/start', { params: { path: { key } } }))
}

/** `canopy stop`, or `canopy stop --now` with `now`, which also ends the run working it. */
export async function stopTicket(key: string, now: boolean): Promise<Stopped> {
    return unwrap(await api.POST('/api/tickets/{key}/stop', { params: { path: { key } }, body: { now } }))
}

/** `canopy forget`, with the key as the operator typed it: the server refuses `not_confirmed` unless it matches. */
export async function forgetTicket(key: string, confirm: string): Promise<Forgot> {
    return unwrap(await api.POST('/api/tickets/{key}/forget', { params: { path: { key } }, body: { confirm } }))
}

/** `canopy reply`: a message on the ticket for the next tick to read. `submission` makes a resend a no-op. */
export async function replyTicket(key: string, body: string, submission: string): Promise<Replied> {
    return unwrap(
        await api.POST('/api/tickets/{key}/replies', { params: { path: { key } }, body: { body, submission } }),
    )
}

/** A note to a chore, as `canopy reply chore:NAME`: its next runs read it (DESIGN §19). */
export async function replyChore(name: string, body: string, submission: string): Promise<Replied> {
    return unwrap(
        await api.POST('/api/chores/{name}/replies', { params: { path: { name } }, body: { body, submission } }),
    )
}

/** `canopy pause`: the loop starts no tick until it is resumed. A tick already running finishes. */
export async function pauseLoop(): Promise<PauseChanged> {
    return unwrap(await api.POST('/api/loop/pause'))
}

/** `canopy resume`: the loop ticks when its wait runs out, at once if it already has. */
export async function resumeLoop(): Promise<PauseChanged> {
    return unwrap(await api.POST('/api/loop/resume'))
}

/**
 * Ask the loop to read its config files again, as SIGHUP does (DESIGN §6). A file that does not load is refused
 * (`config_invalid`) and the loop keeps the config it has.
 */
export async function reloadConfig(): Promise<ConfigReload> {
    return unwrap(await api.POST('/api/loop/reload'))
}

/** After a pause or a resume: show the state it left now, rather than wait for the stream. */
export function showLoop(client: QueryClient, loop: LoopState): void {
    client.setQueryData(keys.loop, loop)
}

/** After a note to a chore: read it again now, rather than wait for the stream. */
export function refreshChore(client: QueryClient, name: string): Promise<void> {
    return client.invalidateQueries({ queryKey: keys.chore(name) })
}

/** After an action on a ticket: read it again now, rather than wait for the stream to say it changed. */
export function refreshTicket(client: QueryClient, key: string): Promise<void> {
    return client.invalidateQueries({ queryKey: keys.ticket(key) })
}

/** A submission id for a reply form, drawn when the form is rendered and kept until the reply is recorded. */
export function newSubmission(): string {
    return crypto.randomUUID()
}
