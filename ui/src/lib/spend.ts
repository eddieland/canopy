// The spend page (ROADMAP M33): what each local day, or hour, cost, by kind, and what the overseer's ticks bought. The
// numbers are the server's (`canopy spend`); this lays them out.

import type { SpendBreakdownRange } from '@/api/queries'
import type { SpendBreakdown, SpendCosts, SpendDay, SpendGroup, SpendTicket } from '@/api/types'
import { costText } from '@/lib/cost-total'
import { counted } from '@/lib/descriptions'

/** The window the page opens on, as `canopy spend` does: the week. */
export const DEFAULT_WINDOW: SpendBreakdownRange = { days: 7 }

/** The windows the page offers, shortest first. */
export const SPEND_WINDOWS: readonly SpendBreakdownRange[] = [{ hours: 24 }, DEFAULT_WINDOW, { days: 30 }]

/** A series of the by-day chart: a part of a day's spend no other series counts. */
export type SeriesKey = 'idle' | 'overseer' | 'workers' | 'triage' | 'plans' | 'chores' | 'reviews' | 'dry_run'

/**
 * One series: what it counts, its name, what that name means on hover, and its fill, written out so Tailwind finds
 * it. Its name is the same in the totals, the legend, the table, and a bar's hover.
 */
export interface Series {
    /** What it counts, as `canopy spend` does: `overseer` is the live overseer's whole spend, idle ticks' included. */
    key: SeriesKey
    /** Its name, everywhere the page says it. */
    label: string
    /** What it counts, on its name's hover. */
    hint: string
    /** Its fill: a spend token, never a state's color. */
    fill: string
}

/**
 * The series bottom up. Idle ticks first, on the baseline under the rest of the overseer's, a deeper shade of the same
 * hue, so the two read as one: together they are the overseer's bar, and idle ticks a part of it. Then the runs the
 * overseer started, a triage before a plan and the plan among them, then dry runs. Idle spend is a sliver beside a
 * worker's, so its trend across days is read from the table, not the bars.
 */
export const SERIES: readonly Series[] = [
    {
        key: 'idle',
        label: 'idle ticks',
        hint: "The part of the overseer's spend its idle ticks made, drawn under the rest of it",
        fill: 'bg-spend-idle',
    },
    {
        key: 'overseer',
        label: 'overseer',
        hint: "The live overseer's whole spend, idle ticks' included, as canopy spend counts it",
        fill: 'bg-spend-overseer',
    },
    {
        key: 'workers',
        label: 'workers',
        hint: 'The workers the overseer started',
        fill: 'bg-spend-workers',
    },
    {
        key: 'triage',
        label: 'plan triage',
        hint: 'The triage runs, needs-plan, that judged whether a ticket needed its plan, on runtime.plan_triage_cmd',
        fill: 'bg-spend-triage',
    },
    {
        key: 'plans',
        label: 'plans',
        hint: "The plan runs that wrote tickets' plans: what a plan triage waived would have cost",
        fill: 'bg-spend-plans',
    },
    { key: 'chores', label: 'chores', hint: 'The chores canopy ran', fill: 'bg-spend-chores' },
    { key: 'reviews', label: 'reviews', hint: "canopy's reviews of PRs", fill: 'bg-spend-reviews' },
    { key: 'dry_run', label: 'dry runs', hint: 'Dry-run ticks, apart from the live ones', fill: 'bg-spend-dry-run' },
]

/** Each group of ticks in words, as `canopy spend` prints it. */
export const GROUP_LABEL: Record<SpendGroup, string> = {
    idle: 'idle',
    busy: 'not idle',
    hand_run: 'hand-run',
    not_ok: 'not ok',
    dry_run: 'dry run',
}

/** What each group means, on hover. */
export const GROUP_HINT: Record<SpendGroup, string> = {
    idle: 'The loop started no work: it dispatched nothing, and nothing reached the journal before it',
    busy: 'The loop ran it and it was not idle: it dispatched, or a run ended or you acted before it',
    hand_run: 'canopy tick, run by hand: no loop said whether it was idle',
    not_ok: 'It ended other than ok: skipped, failed, or abandoned',
    dry_run: 'A dry run: it planned and acted on nothing',
}

/**
 * The spend page's description, the window's state: what it cost and what it got done, as
 * `$10.51 over 7 days · 2 tickets done`. What the page shows on every visit is its title's help.
 */
export function spendLine(found: Pick<SpendBreakdown, 'days' | 'hours' | 'done' | 'totals'>): string {
    return `${costText(found.totals.total)} over ${windowName(found)} · ${counted(found.done, 'ticket')} done`
}

/** A window's length in words, from its search params or the breakdown read over it: `24 hours`, `7 days`. */
export function windowName(range: { days?: number | null; hours?: number | null }): string {
    const [n, unit] =
        range.hours === undefined || range.hours === null ? [range.days ?? 0, 'day'] : [range.hours, 'hour']
    return n === 1 ? `1 ${unit}` : `${n} ${unit}s`
}

/** A window's id, its toggle's value and test id: the hours with an `h`, `24h`, or the days, `7`. */
export function windowId(range: SpendBreakdownRange): string {
    return range.hours === undefined ? String(range.days) : `${range.hours}h`
}

/** The window the search params name, if the page offers it: hours before days; undefined for the default. */
export function spendWindow(search: { days?: unknown; hours?: unknown }): SpendBreakdownRange | undefined {
    return (
        SPEND_WINDOWS.find((w) => w.hours !== undefined && names(search.hours, w.hours)) ??
        SPEND_WINDOWS.find((w) => w.days !== undefined && names(search.days, w.days))
    )
}

// Whether a search param names `n`, as a number or as its digits.
function names(value: unknown, n: number): boolean {
    return n === value || String(n) === value
}

/**
 * What a series' segment of a bar draws: idle ticks' part taken out of the overseer's, so the stack counts no dollar
 * twice and the two segments together are the overseer's. The totals, the table, and a bar's hover say the overseer's
 * whole, as `canopy spend` does.
 */
export function seriesCost(costs: SpendCosts, key: SeriesKey): number {
    if (key === 'overseer') {
        return Math.max(0, (costs.overseer ?? 0) - (costs.idle ?? 0))
    }
    return costs[key] ?? 0
}

/** The tallest day's (or hour's) total, the chart's top; 0 when nothing in the window reported a cost. */
export function chartTop(days: SpendDay[]): number {
    return Math.max(0, ...days.map((day) => day.costs.total ?? 0))
}

/** Where the dearest day is in the window, the latest of any equal, so its total is said over its bar; -1 for none. */
export function dearestDay(days: SpendDay[]): number {
    const top = chartTop(days)
    return top === 0 ? -1 : days.findLastIndex((day) => day.costs.total === top)
}

/**
 * A day's bar on hover: its date, its total, and each series it has, by the names the legend gives them. The overseer
 * says its whole, as the totals do, with idle ticks' part of it after it: `overseer $1.00 (idle ticks $0.25)`.
 */
export function dayHint(day: SpendDay): string {
    const said = (series: Series) => `${series.label} ${costText(day.costs[series.key])}`
    const idle = SERIES.find((series) => series.key === 'idle')
    const ofIt = idle !== undefined && (day.costs.idle ?? 0) > 0 ? ` (${said(idle)})` : ''
    const parts = SERIES.filter((series) => series.key !== 'idle' && (day.costs[series.key] ?? 0) > 0).map((series) =>
        series.key === 'overseer' ? `${said(series)}${ofIt}` : said(series),
    )
    const total = day.costs.total === null ? 'nothing reported' : costText(day.costs.total)
    const name = dayName(day.day)
    return parts.length === 0 ? `${name}: ${total}` : `${name}: ${total}, ${parts.join(', ')}`
}

/**
 * A day as the server names it, `2026-10-07`, as the chart's axis says it: `Oct 7`, whatever the browser's zone. An
 * hour, `2026-10-07T14`, is its time alone, `14:00`, as an axis of hours reads.
 */
export function dayLabel(day: string): string {
    const hour = day.split('T')[1]
    return hour === undefined ? dateLabel(day) : `${hour}:00`
}

/** A day or an hour in full, as its row and its bar's hover say it: `Oct 7`, or with its time, `Oct 7, 14:00`. */
export function dayName(day: string): string {
    const [date = day, hour] = day.split('T')
    return hour === undefined ? dateLabel(date) : `${dateLabel(date)}, ${hour}:00`
}

function dateLabel(day: string): string {
    const [year, month, date] = day.split('-').map(Number)
    return new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1, date ?? 1)).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        timeZone: 'UTC',
    })
}

/** A share, 0 to 1, as a whole percent: `41%`, or a dash when there is none. */
export function shareText(share: number | null): string {
    return share === null ? '–' : `${Math.round(share * 100)}%`
}

/** When and how a ticket was marked done in the window, on the operator's day: `Oct 7, merged`; empty when not. */
export function doneText(ticket: Pick<SpendTicket, 'done' | 'done_at'>): string {
    return ticket.done === null || ticket.done_at === null
        ? ''
        : `${new Date(ticket.done_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}, ${ticket.done}`
}
