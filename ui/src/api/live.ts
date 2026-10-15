import type { QueryClient } from '@tanstack/react-query'

import { keys } from './queries'
import type { ChoreRunDetail, LastTick, Run, StreamEvent } from './types'

/**
 * Writes one stream event into the Query cache. A list arrives whole and replaces the cached one; a changed ticket is
 * read again, only if a page shows it, and so is a chore's page whenever the chores change, and the ticks and the
 * ticket shown whenever the latest tick does. The worktrees are not on the stream: a run starting or ending, or
 * changing the worktrees it holds, marks them stale, and they are read again only if a page shows them. A transcript
 * is read again when its run's or chore run's status or its tick changes, the only times its log can. The loop's
 * pause arrives whole, as a list does. Unknown event types are ignored, so the server can add some.
 */
export function applyStreamEvent(client: QueryClient, event: StreamEvent): void {
    switch (event.type) {
        case 'attention.updated': {
            client.setQueryData(keys.attention, event.items)
            break
        }
        case 'runs.updated': {
            const before = client.getQueryData<Run[]>(keys.runs)
            client.setQueryData(keys.runs, event.runs)
            if (before !== undefined && holding(before) !== holding(event.runs)) {
                void client.invalidateQueries({ queryKey: keys.worktrees, refetchType: 'active' })
            }
            // A run that started or ended changes the spend page's counts of runs, even one that reported no cost.
            if (before !== undefined && statuses(before) !== statuses(event.runs)) {
                void client.invalidateQueries({ queryKey: ['spend', 'breakdown'], refetchType: 'active' })
            }
            // A run a page holds is written whole; its transcript is read again only when its status moves, since a
            // run's events reach its log when it ends and its cost moves more often than that.
            for (const run of event.runs) {
                const shown = client.getQueryData<Run>(keys.run(run.id))
                if (shown === undefined) {
                    continue
                }
                client.setQueryData(keys.run(run.id), run)
                if (shown.status !== run.status) {
                    void client.invalidateQueries({ queryKey: keys.runTranscript(run.id) })
                }
            }
            break
        }
        case 'tickets.updated': {
            client.setQueryData(keys.tickets, event.tickets)
            break
        }
        case 'chores.updated': {
            client.setQueryData(keys.chores, event.chores)
            void client.invalidateQueries({ queryKey: ['chore'], refetchType: 'active' })
            // A chore run that ended changes the spend page's counts of runs, even one that reported no cost.
            void client.invalidateQueries({ queryKey: ['spend', 'breakdown'], refetchType: 'active' })
            // A chore run's page and transcript change only as it ends, when its status moves.
            for (const chore of event.chores) {
                for (const run of [chore.running, chore.latest]) {
                    if (!run) {
                        continue
                    }
                    const shown = client.getQueryData<ChoreRunDetail>(keys.choreRun(chore.name, run.id))
                    if (shown === undefined || shown.run.status === run.status) {
                        continue
                    }
                    void client.invalidateQueries({ queryKey: keys.choreRun(chore.name, run.id) })
                    void client.invalidateQueries({ queryKey: keys.choreRunTranscript(chore.name, run.id) })
                }
            }
            break
        }
        case 'ticket.changed': {
            void client.invalidateQueries({ queryKey: keys.ticket(event.key), refetchType: 'active' })
            // A run of the ticket started or ended: the runs a PR's page shows, and the PRs list's run working now.
            void client.invalidateQueries({ queryKey: keys.pullRequests, refetchType: 'active' })
            break
        }
        case 'spend.updated': {
            client.setQueryData(keys.spend, event.spend)
            // The spend page's breakdown, which the stream does not carry: refetched only while a page shows it.
            void client.invalidateQueries({ queryKey: ['spend', 'breakdown'], refetchType: 'active' })
            break
        }
        case 'tick.updated': {
            const before = client.getQueryData<LastTick>(keys.tick)?.tick
            client.setQueryData(keys.tick, { tick: event.tick, acknowledged: event.acknowledged })
            // Only the latest tick's output can still change, and only as it ends.
            if (event.tick && (before?.id !== event.tick.id || before.status !== event.tick.status)) {
                void client.invalidateQueries({ queryKey: keys.tickTranscript(event.tick.id) })
            }
            // A tick started, ended, or recorded a decision: the ticks, a tick's page, and a ticket's decisions. A
            // review run ends between two ticks, so the reviews go with them.
            void client.invalidateQueries({ queryKey: keys.ticks, refetchType: 'active' })
            void client.invalidateQueries({ queryKey: ['ticket'], refetchType: 'active' })
            void client.invalidateQueries({ queryKey: keys.reviews, refetchType: 'active' })
            // A PR's phase, decisions, and reviews move with the ticks too, and the spend page's idle ticks.
            void client.invalidateQueries({ queryKey: keys.pullRequests, refetchType: 'active' })
            void client.invalidateQueries({ queryKey: ['spend', 'breakdown'], refetchType: 'active' })
            break
        }
        case 'loop.updated': {
            client.setQueryData(keys.loop, { paused: event.paused, notice: event.notice })
            break
        }
    }
}

/** Each run's state, as one comparable string: a run starting or ending changes it, a cost going up does not. */
function statuses(runs: Run[]): string {
    return runs.map((run) => `${run.id}:${run.state}`).join(',')
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
    'chores.updated': 'chores',
}

/** Parses an SSE `data` payload into a StreamEvent, or null when it is not one this UI knows. */
export function parseStreamEvent(data: string): StreamEvent | null {
    let value: unknown
    try {
        value = JSON.parse(data)
    } catch {
        return null
    }
    if (typeof value !== 'object' || value === null || !('type' in value)) {
        return null
    }
    const type = value.type
    if (typeof type !== 'string') {
        return null
    }
    const list = LISTS[type]
    if (list !== undefined) {
        return Array.isArray((value as Record<string, unknown>)[list]) ? (value as StreamEvent) : null
    }
    if (type === 'ticket.changed' && typeof (value as { key?: unknown }).key === 'string') {
        return value as StreamEvent
    }
    if (type === 'tick.updated') {
        const { tick, acknowledged } = value as { tick?: unknown; acknowledged?: unknown }
        // `typeof null` is 'object' too: a tick, or null for none.
        const known = typeof tick === 'object'
        return known && (acknowledged === null || typeof acknowledged === 'number') ? (value as StreamEvent) : null
    }
    if (type === 'loop.updated') {
        const { paused, notice } = value as { paused?: unknown; notice?: unknown }
        // `typeof null` is 'object' too: running is `paused: null`, no notice `notice: null`, and a missing key is no
        // event.
        return typeof paused === 'object' && typeof notice === 'object' ? (value as StreamEvent) : null
    }
    if (type === 'spend.updated') {
        const spend = (value as { spend?: unknown }).spend
        return typeof spend === 'object' && spend !== null ? (value as StreamEvent) : null
    }
    return null
}
