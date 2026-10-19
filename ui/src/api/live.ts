import type { QueryClient } from '@tanstack/react-query'

import { keys } from './queries'
import type { ChoreRun, ChoreRunDetail, LastTick, Run, StreamEvent, Tick } from './types'

/**
 * Writes one stream event into the Query cache. A list arrives whole and replaces the cached one, canopy's reviews
 * among them; a changed ticket is read again, only if a page shows it, and so is a chore's page whenever the chores
 * change, and the ticks and the ticket shown whenever the latest tick does. The worktrees are not on the stream: a run
 * starting or ending, or changing the worktrees it holds, marks them stale, and they are read again only if a page
 * shows them. A run's transcript is read again when its status, latest tool call, or cost moves, as its worker prints;
 * a chore run's when its status does, and a tick's when the tick changes, the only times their logs can. The loop's
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
            // A run a page holds is written whole; its transcript and output are read again when its log has more in
            // it: its worker's events reach the log as it prints them, and a new tool call or model call moves its row.
            for (const run of event.runs) {
                const shown = client.getQueryData<Run>(keys.run(run.id))
                if (shown === undefined) {
                    continue
                }
                client.setQueryData(keys.run(run.id), run)
                if (logged(shown) !== logged(run)) {
                    void client.invalidateQueries({ queryKey: keys.runTranscript(run.id) })
                }
                // A run writes its memory as it ends.
                if (shown.status !== run.status) {
                    void client.invalidateQueries({ queryKey: keys.runMemory(run.id) })
                }
            }
            break
        }
        case 'reviews.updated': {
            client.setQueryData(keys.reviews, event.reviews)
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
            // A chore run's page and transcript are read again when its log has more in it: its agent's events reach
            // the log as it prints them, and each model call's end moves its cost; its status moves as it ends.
            for (const chore of event.chores) {
                for (const run of [chore.running, chore.latest]) {
                    if (!run) {
                        continue
                    }
                    const shown = client.getQueryData<ChoreRunDetail>(keys.choreRun(chore.name, run.id))
                    if (shown === undefined || choreLogged(shown.run) === choreLogged(run)) {
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
            // Only the latest tick's output can still change: its overseer's events reach the log as it prints them,
            // and each model call's end moves its cost, each decision its count, and its end its status.
            if (
                event.tick &&
                (!before || before.id !== event.tick.id || tickLogged(before) !== tickLogged(event.tick))
            ) {
                void client.invalidateQueries({ queryKey: keys.tickTranscript(event.tick.id) })
            }
            // A tick started, ended, or recorded a decision: the ticks, a tick's page, and a ticket's decisions. A
            // review run ends between two ticks, so a review's page goes with them; the list arrives on the stream.
            void client.invalidateQueries({ queryKey: keys.ticks, refetchType: 'active' })
            void client.invalidateQueries({ queryKey: ['ticket'], refetchType: 'active' })
            void client.invalidateQueries({ queryKey: keys.reviews, refetchType: 'active' })
            // A tick expires proposals, and the runs it saw end wrote memory.
            void client.invalidateQueries({ queryKey: keys.memory, refetchType: 'active' })
            // A PR's phase, decisions, and reviews move with the ticks too, and the spend page's idle ticks.
            void client.invalidateQueries({ queryKey: keys.pullRequests, refetchType: 'active' })
            void client.invalidateQueries({ queryKey: ['spend', 'breakdown'], refetchType: 'active' })
            break
        }
        case 'loop.updated': {
            client.setQueryData(keys.loop, { paused: event.paused, notice: event.notice, memory: event.memory })
            break
        }
    }
}

/** Each run's state, as one comparable string: a run starting or ending changes it, a cost going up does not. */
function statuses(runs: Run[]): string {
    return runs.map((run) => `${run.id}:${run.state}`).join(',')
}

/**
 * What of a run's row moves as its log grows, as one comparable string: its status, its latest tool call, and its
 * cost, which moves at each model call.
 */
function logged(run: Run): string {
    return `${run.status}:${run.activity?.at ?? ''}:${run.cost_usd ?? ''}`
}

/** What moves as a running chore run's log grows: its status, and its cost at each model call's end. */
function choreLogged(run: ChoreRun): string {
    return `${run.status}:${run.cost_usd ?? ''}`
}

/** What moves as a running tick's log grows: its status, its overseer's cost, and how many decisions it recorded. */
function tickLogged(tick: Tick): string {
    return `${tick.status}:${tick.cost_usd ?? ''}:${tick.decisions}`
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
    'reviews.updated': 'reviews',
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
        const { paused, notice, memory } = value as { paused?: unknown; notice?: unknown; memory?: unknown }
        // `typeof null` is 'object' too: running is `paused: null`, no notice `notice: null`, memory off
        // `memory: null`, and a missing key is no event.
        return typeof paused === 'object' && typeof notice === 'object' && typeof memory === 'object'
            ? (value as StreamEvent)
            : null
    }
    if (type === 'spend.updated') {
        const spend = (value as { spend?: unknown }).spend
        return typeof spend === 'object' && spend !== null ? (value as StreamEvent) : null
    }
    return null
}
