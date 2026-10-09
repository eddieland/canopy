import type { ChoreSummary, Message } from '@/api/types'
import { age } from '@/lib/time'

/** When a chore may start (D099), as `canopy chore run` names it when it refuses: `mon,tue 08:00-18:00 UTC`. */
export function windowText(chore: Pick<ChoreSummary, 'days' | 'hours' | 'timezone'>): string {
    if (chore.days.length === 0 && chore.hours === null) return 'any time'
    const days = chore.days.length > 0 ? chore.days.join(',') : 'every day'
    return `${days} ${chore.hours ?? 'all day'} ${chore.timezone ?? 'local time'}`
}

/** When the harness next lets the chore start: `due now`, or `due in 1h`. Whether it runs then is the overseer's. */
export function dueText(chore: Pick<ChoreSummary, 'due_at'>, now: number): string {
    if (chore.due_at === null || Date.parse(chore.due_at) <= now) return 'due now'
    return `due in ${age(new Date(now).toISOString(), Date.parse(chore.due_at))}`
}

/** A chore on one line, as `canopy status` says it: running, or its latest run and when it is next due. */
export function choreLine(chore: Pick<ChoreSummary, 'running' | 'latest' | 'due_at'>, now: number): string {
    if (chore.running !== null) return `running for ${age(chore.running.started_at, now)}`
    const last =
        chore.latest === null ? 'never run' : `last ${chore.latest.status} ${age(chore.latest.started_at, now)} ago`
    return `${last}, ${dueText(chore, now)}`
}

/**
 * Whether a note to a chore came after its latest run started, so no run has read it yet (docs/DESIGN.md §19): the
 * chore's next run does. Notes wake nothing and no tick reads them, so a tick's acknowledgement says nothing here.
 */
export function awaitsRun(note: Pick<Message, 'at'>, chore: Pick<ChoreSummary, 'running' | 'latest'>): boolean {
    const last = chore.running?.started_at ?? chore.latest?.started_at
    return last === undefined || Date.parse(note.at) > Date.parse(last)
}
