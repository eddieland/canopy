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

/** A ticket's runs working now, oldest first. The harness runs one worker per ticket, so there is at most one. */
export function workingOn(runs: Run[], ticketKey: string): Run[] {
    return runs
        .filter((r) => r.state === 'running' && r.ticket_key === ticketKey)
        .toSorted((a, b) => a.started_at.localeCompare(b.started_at))
}

/**
 * The runs the rail lists, at most `limit`: those running first, then those waiting on the operator's answer, each
 * oldest first, so the work in progress leads and holds the slots. `more` counts the ones left out.
 */
export function railRuns(runs: Run[], limit: number): { shown: Run[]; more: number } {
    const working = runs
        .filter((r) => r.state === 'blocked' || r.state === 'running')
        .toSorted((a, b) => rank(a) - rank(b) || a.started_at.localeCompare(b.started_at))
    return { shown: working.slice(0, limit), more: Math.max(working.length - limit, 0) }
}

function rank(run: Run): number {
    return run.state === 'running' ? 0 : 1
}
