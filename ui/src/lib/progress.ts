// A run's progress as one checklist (DESIGN §41): its steps when it named any, else what is done, what it does now,
// and what is next, which its meter and its page both draw.
import type { RunCard } from '@/api/types'

/** Whether a running run's progress is stale at `now`: too many tool calls since its last update, as the server says,
 * or its time to go stale has come. An ended run's never is. */
export function isStale(card: RunCard, now: number): boolean {
    return card.stale || (card.stale_at !== null && now >= Date.parse(card.stale_at))
}

/** Where one entry of the checklist stands: a step's status, with `stuck` for a working step past its time. */
export type ItemStatus = RunCard['steps'][number]['status'] | 'stuck'

/** One entry of the checklist: a step, or one of what is done, what it does now, and what is next. */
export interface Item {
    /** What it is, in the agent's words. */
    title: string
    /** Where it stands. */
    status: ItemStatus
    /** The stage it belongs to, for a step that names one. */
    stage: string | null
    /** The proof of a done entry, for one taken from what is done. */
    proof: string | null
}

/**
 * The work as one list: its steps when it named any, a working step past its `stuck_at` marked stuck at `now`; else
 * what is done, what it does now, and what is next, in that order, as if each were a step.
 */
export function checklist(card: RunCard, now: number): Item[] {
    if (card.steps.length > 0) {
        return card.steps.map((step) => ({
            title: step.title,
            status: step.stuck_at !== null && now >= Date.parse(step.stuck_at) ? 'stuck' : step.status,
            stage: step.stage ?? null,
            proof: null,
        }))
    }
    return [
        ...card.done.map((d) => ({ title: d.step, status: 'done' as const, stage: null, proof: d.proof })),
        { title: card.now, status: 'working' as const, stage: null, proof: null },
        ...card.next.map((n) => ({ title: n, status: 'not_started' as const, stage: null, proof: null })),
    ]
}
