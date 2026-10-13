import type { ChoreSpendWindow, ChoreSummary, Message } from '@/api/types'
import { age } from '@/lib/time'

/** When a chore may start, as `canopy chore run` names it when it refuses: `mon,tue 08:00-18:00 UTC`. */
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
 * Whether a note to a chore came after its latest run started, so no run has read it yet (DESIGN §19): the
 * chore's next run does. Notes wake nothing and no tick reads them, so a tick's acknowledgement says nothing here.
 */
export function awaitsRun(note: Pick<Message, 'at'>, chore: Pick<ChoreSummary, 'running' | 'latest'>): boolean {
    const last = chore.running?.started_at ?? chore.latest?.started_at
    return last === undefined || Date.parse(note.at) > Date.parse(last)
}

/** A cost in dollars, as every cost in the UI is shown, or a dash when nothing reported one. */
export function costText(cost: number | null): string {
    return cost === null ? '–' : `$${cost.toFixed(2)}`
}

/**
 * What a chore's runs in one window cost, in words: `$0.87 over 4 runs, $0.29 a run, 1 reported none`. The cost a
 * run is over the runs that reported one, so a run that reported nothing does not pull it down.
 */
export function spendText(window: ChoreSpendWindow): string {
    const runs = window.runs === 1 ? '1 run' : `${window.runs} runs`
    if (window.runs === 0) return 'no runs'
    if (window.cost_usd === null) return `${runs}, none reported a cost`
    const parts = [`${costText(window.cost_usd)} over ${runs}`]
    if (window.priced > 1) parts.push(`${costText(window.cost_usd / window.priced)} a run`)
    const unpriced = window.runs - window.priced
    if (unpriced > 0) parts.push(`${unpriced} reported none`)
    return parts.join(', ')
}
