import type { Run, RunState } from '@/api/types'

// Full class names, written out, so Tailwind finds them. One entry per state; the types make a missing one an error.

/** Each run state's dot: its status color as a fill. */
export const RUN_DOT: Record<RunState, string> = {
    running: 'bg-status-running',
    blocked: 'bg-status-blocked',
    stopped: 'bg-status-stopped',
    done: 'bg-status-done',
    failed: 'bg-status-failed',
}

/** Each run state's text color. */
export const RUN_TEXT: Record<RunState, string> = {
    running: 'text-status-running',
    blocked: 'text-status-blocked',
    stopped: 'text-status-stopped',
    done: 'text-status-done',
    failed: 'text-status-failed',
}

/** One ticket's runs on the runs page: the latest, which says where the ticket stands, over the ones before it. */
export interface TicketRuns {
    /** The ticket's latest run: its running one, else the one that ended last. */
    latest: Run
    /** Its runs before that, newest first. */
    earlier: Run[]
}

/**
 * `runs`, in the order the server sends them, one entry per ticket, in the order of each ticket's latest run. A ticket
 * that asked a question, got its answer, and asked again is one entry, not two blocked ones.
 */
export function byTicket(runs: Run[]): TicketRuns[] {
    // The server sends the running runs first, then the rest newest first, and runs one worker per ticket at a time:
    // a ticket's first run in the list is its latest.
    const groups = new Map<string, TicketRuns>()
    for (const run of runs) {
        const group = groups.get(run.ticket_key)
        if (group === undefined) {
            groups.set(run.ticket_key, { latest: run, earlier: [] })
        } else {
            group.earlier.push(run)
        }
    }
    return [...groups.values()]
}

/** Each ticket's latest run, so a question a later run took up no longer counts as waiting. */
export function latestRuns(runs: Run[]): Run[] {
    return byTicket(runs).map((g) => g.latest)
}

/** A ticket's runs working now, oldest first. The harness runs one worker per ticket, so there is at most one. */
export function workingOn(runs: Run[], ticketKey: string): Run[] {
    return runs
        .filter((r) => r.state === 'running' && r.ticket_key === ticketKey)
        .toSorted((a, b) => a.started_at.localeCompare(b.started_at))
}

/**
 * The runs the rail lists, at most `limit`: those running first, then those waiting on the operator's answer, each
 * oldest first, so the work in progress leads and holds the slots. `more` counts the ones left out. Only each ticket's
 * latest run counts: a blocked run a later one followed waits on nothing.
 */
export function railRuns(runs: Run[], limit: number): { shown: Run[]; more: number } {
    const working = latestRuns(runs)
        .filter((r) => r.state === 'blocked' || r.state === 'running')
        .toSorted((a, b) => {
            const order = rank(a) - rank(b)
            return order === 0 ? a.started_at.localeCompare(b.started_at) : order
        })
    return { shown: working.slice(0, limit), more: Math.max(working.length - limit, 0) }
}

function rank(run: Run): number {
    return run.state === 'running' ? 0 : 1
}
