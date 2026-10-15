import type { ChoreFinding, ChoreSpendWindow, ChoreSummary, Message, RunState } from '@/api/types'
import { age } from '@/lib/time'

/**
 * How often a chore may start, as `canopy chore run` says it when it refuses one too soon: `every 360 minutes`. In
 * minutes, as `every_minutes` in the config, so it reads as the operator wrote it.
 */
export function cadenceText(minutes: number): string {
    return minutes === 1 ? 'every minute' : `every ${minutes} minutes`
}

/**
 * A chore run's state from its status, as the server groups it: one that checked is done, one still going is running,
 * and every other ending is failed, since it raises `chore_failed` (DESIGN §19).
 */
export function choreRunState(status: string): RunState {
    if (status === 'running') {
        return 'running'
    }
    return status === 'ok' ? 'done' : 'failed'
}

/** When a chore may start, as `canopy chore run` names it when it refuses: `mon,tue 08:00-18:00 UTC`. */
export function windowText(chore: Pick<ChoreSummary, 'days' | 'hours' | 'timezone'>): string {
    if (chore.days.length === 0 && chore.hours === null) {
        return 'any time'
    }
    const days = chore.days.length > 0 ? chore.days.join(',') : 'every day'
    return `${days} ${chore.hours ?? 'all day'} ${chore.timezone ?? 'local time'}`
}

/** When the harness next lets the chore start: `due now`, or `due in 1h`. Whether it runs then is the overseer's. */
export function dueText(chore: Pick<ChoreSummary, 'due_at'>, now: number): string {
    if (chore.due_at === null || Date.parse(chore.due_at) <= now) {
        return 'due now'
    }
    return `due in ${age(new Date(now).toISOString(), Date.parse(chore.due_at))}`
}

/** A chore on one line, as `canopy status` says it: running, or its latest run and when it is next due. */
export function choreLine(chore: Pick<ChoreSummary, 'running' | 'latest' | 'due_at'>, now: number): string {
    if (chore.running !== null) {
        return `running for ${age(chore.running.started_at, now)}`
    }
    const last =
        chore.latest === null ? 'never run' : `last ${chore.latest.status} ${age(chore.latest.started_at, now)} ago`
    return `${last}, ${dueText(chore, now)}`
}

/**
 * Whether a note to a chore came after its latest run started, so no run has read it yet (DESIGN §19): the
 * chore's next run does. Notes wake nothing and no tick reads them, so a tick's acknowledgement says nothing here.
 */
export function awaitsRun(note: Pick<Message, 'at'>, chore: Pick<ChoreSummary, 'running' | 'latest'>): boolean {
    const last = chore.running?.started_at ?? chore.latest?.started_at
    return last === undefined || Date.parse(note.at) > Date.parse(last)
}

/** How many of a chore's runs started in a window, and how many of them reported no cost: `4, 1 unpriced`. */
export function runsText(window: Pick<ChoreSpendWindow, 'runs' | 'priced'>): string {
    const unpriced = window.runs - window.priced
    return unpriced > 0 ? `${window.runs}, ${unpriced} unpriced` : String(window.runs)
}

/**
 * A chore's findings as its line in the list counts them: those still waiting on the operator, then how many the
 * operator dismissed, as `canopy status` counts them (DESIGN §19): `1 open finding · 2 dismissed`. A dismissed one is
 * still reported, only off the attention list, so counting it as open would leave a chore whose findings were all
 * dismissed looking as if they waited.
 */
export function findingsText(findings: readonly Pick<ChoreFinding, 'dismissed'>[]): string {
    const dismissed = findings.filter((f) => f.dismissed).length
    const waiting = findings.length - dismissed
    const open = waiting === 1 ? '1 open finding' : `${waiting} open findings`
    return dismissed > 0 ? `${open} · ${dismissed} dismissed` : open
}
