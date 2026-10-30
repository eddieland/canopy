// The spend page (ROADMAP M33): what each local day, or hour, cost, by kind, and what the overseer's ticks bought. The
// numbers are the server's (`canopy spend`); this lays them out.

import type { SpendBreakdownRange } from '@/api/queries'
import { SPEND_KINDS } from '@/api/types'
import type {
    SpendBreakdown,
    SpendCosts,
    SpendDay,
    SpendGroup,
    SpendKind,
    SpendModel,
    SpendMonth,
    SpendSessions,
    SpendTicket,
    SpendTool,
} from '@/api/types'
import type { Clock } from '@/lib/clock'
import { costText } from '@/lib/cost-total'
import { counted } from '@/lib/descriptions'
import type { RunsOf } from '@/lib/run-state'
import { clockTime, stamp } from '@/lib/time'

/** The window the page opens on, as `canopy spend` does: the week. */
export const DEFAULT_WINDOW: SpendBreakdownRange = { days: 7 }

/** The windows the page offers, shortest first. */
export const SPEND_WINDOWS: readonly SpendBreakdownRange[] = [{ hours: 24 }, DEFAULT_WINDOW, { days: 30 }]

/**
 * The window a ticket's worker spend by model covers on its page, as the server reads it (`TICKET_MODEL_DAYS` in
 * canopy.serve.views): the page's longest, which the ticket's line opens.
 */
export const TICKET_MODEL_WINDOW = { days: 30 } as const satisfies SpendBreakdownRange

// What the server divides a tool's characters by to estimate its tokens (`CHARS_PER_TOKEN` in canopy.core.spend).
const CHARS_PER_TOKEN = 4

/** A series of the by-day chart: a part of a day's spend no other series counts. */
export type SeriesKey =
    | 'idle'
    | 'overseer'
    | 'workers'
    | 'plans'
    | 'chores'
    | 'reviews'
    | 'tasks'
    | 'dry_run'
    | 'outside'

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
 * overseer started, the plans among them, then your tasks' runs, then dry runs, then the sessions outside canopy, on
 * top as no part of canopy's work. Idle spend is a sliver beside a worker's, so its trend across days is read from the
 * table, not the bars.
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
        key: 'plans',
        label: 'plans',
        hint: "The plan runs that wrote tickets' plans, old needs-plan triage runs among them",
        fill: 'bg-spend-plans',
    },
    { key: 'chores', label: 'chores', hint: 'The chores canopy ran', fill: 'bg-spend-chores' },
    { key: 'reviews', label: 'reviews', hint: "canopy's reviews of PRs", fill: 'bg-spend-reviews' },
    { key: 'tasks', label: 'tasks', hint: 'The runs of the one-off tasks you submitted', fill: 'bg-spend-tasks' },
    { key: 'dry_run', label: 'dry runs', hint: 'Dry-run ticks, apart from the live ones', fill: 'bg-spend-dry-run' },
    {
        key: 'outside',
        label: 'outside canopy',
        hint: "The runtime's sessions none of canopy's runs started: yours, and other workspaces' canopy",
        fill: 'bg-spend-outside',
    },
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
export function dayHint(day: SpendDay, clock: Clock): string {
    const said = (series: Series) => `${series.label} ${costText(day.costs[series.key])}`
    const idle = SERIES.find((series) => series.key === 'idle')
    const ofIt = idle !== undefined && (day.costs.idle ?? 0) > 0 ? ` (${said(idle)})` : ''
    const parts = SERIES.filter((series) => series.key !== 'idle' && (day.costs[series.key] ?? 0) > 0).map((series) =>
        series.key === 'overseer' ? `${said(series)}${ofIt}` : said(series),
    )
    const total = day.costs.total === null ? 'nothing reported' : costText(day.costs.total)
    const name = dayName(day, clock)
    return parts.length === 0 ? `${name}: ${total}` : `${name}: ${total}, ${parts.join(', ')}`
}

/**
 * A day as the chart's axis says it: the server's name for it, `2026-10-07`, as `Oct 7`, whatever the browser's zone.
 * An hour is the time it starts alone, in the browser's zone on the operator's clock and never with the zone, which
 * the axis has no room for: `14:00`, or `2:00 PM`.
 */
export function dayLabel(day: Pick<SpendDay, 'day' | 'start'>, clock: Clock): string {
    return isHour(day) ? clockTime(day.start, { ...clock, zone: false }) : dateLabel(day.day)
}

/**
 * A day or an hour in full, as its row and its bar's hover say it: `Oct 7`, or an hour as every other time on the
 * page is stamped, in the browser's zone on the operator's clock: `Oct 7 14:00`, `Oct 7 2:00 PM EDT`.
 */
export function dayName(day: Pick<SpendDay, 'day' | 'start'>, clock: Clock): string {
    return isHour(day) ? stamp(day.start, clock) : dateLabel(day.day)
}

// Whether the server named an hour, `2026-10-07T14`, rather than a day.
function isHour(day: Pick<SpendDay, 'day'>): boolean {
    return day.day.includes('T')
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

/** One row of the By model table: a model's runs of one kind, or of every kind summed. */
export type ModelRow = Omit<SpendModel, 'kind'>

/** One row of the By tool table: a tool's calls in one kind's runs, or in every kind's summed. */
export type ToolRow = Omit<SpendTool, 'kind'>

/**
 * The By model table's rows: one kind's as the server sent them, or with no kind each model summed over every kind,
 * the most costly first and the runs no session named a model for last. A run has one kind, so the runs add up.
 */
export function modelRows(models: readonly SpendModel[], kind: SpendKind | undefined): ModelRow[] {
    if (kind !== undefined) {
        return models.filter((m) => m.kind === kind)
    }
    // Each row a copy, its kind left out, so summing into it never changes the query's data.
    const summed = new Map<string | null, ModelRow>()
    for (const { kind: _, ...m } of models) {
        const seen = summed.get(m.model)
        if (seen === undefined) {
            summed.set(m.model, m)
        } else {
            seen.runs += m.runs
            seen.replies += m.replies
            seen.cost_usd = addCost(seen.cost_usd, m.cost_usd)
            seen.workspace_runs = addCost(seen.workspace_runs, m.workspace_runs)
            seen.workspace_cost_usd = addCost(seen.workspace_cost_usd, m.workspace_cost_usd)
        }
    }
    return [...summed.values()].toSorted((a, b) =>
        firstOf(
            Number(a.model === null) - Number(b.model === null),
            (b.cost_usd ?? 0) - (a.cost_usd ?? 0),
            (a.model ?? '').localeCompare(b.model ?? ''),
        ),
    )
}

/**
 * The runs page's kind (`?kind=`) each kind of run is listed under, which By model's links carry: a plan run is a
 * worker run there. Null for the overseer's, whose ticks it lists apart, at `/runs/ticks`, and not by model.
 */
export const RUNS_KIND: Record<SpendKind, RunsOf | null> = {
    overseer: null,
    workers: 'worker',
    plans: 'worker',
    chores: 'chore',
    reviews: 'review',
    tasks: 'task',
}

/** The models the runs page can list runs of: those that served a kind it lists by model (`RUNS_KIND`). */
export function listedModels(models: readonly SpendModel[]): ReadonlySet<string> {
    return new Set(models.flatMap((m) => (m.model === null || RUNS_KIND[m.kind] === null ? [] : [m.model])))
}

/** What a By model row's runs spent each, on average: its cost over its runs; null when they reported none. */
export function perRun(row: ModelRow): number | null {
    return row.cost_usd === null || row.runs === 0 ? null : row.cost_usd / row.runs
}

/**
 * What the workspace's runs of a ticket's By model row's kind and model spent each, on average, the ticket's among
 * them: what its own `perRun` reads against. Null for a row of the whole workspace, or when none reported a cost.
 */
export function workspacePerRun(row: Pick<ModelRow, 'workspace_runs' | 'workspace_cost_usd'>): number | null {
    const runs = row.workspace_runs ?? 0
    const cost = row.workspace_cost_usd ?? null
    return cost === null || runs === 0 ? null : cost / runs
}

/**
 * The kind By model shows: the one `chosen`, or, with none, a ticket's workers', the runs a model override moves, so
 * the reviewer's model does not mix in; undefined for every kind, which `all` chooses while a ticket is set.
 */
export function modelKind(chosen: SpendKind | 'all' | undefined, ticket: string | undefined): SpendKind | undefined {
    if (chosen === 'all') {
        return undefined
    }
    return chosen ?? (ticket === undefined ? undefined : 'workers')
}

/**
 * The models a ticket's page compares, from its worker runs' spend by model: those its sessions named, when more than
 * one did, or one did and the ticket's `override` sets its workers' model. One model alone, on the model config
 * gives every ticket, is the workspace's figure again; none when that is so.
 */
export function comparedModels(models: readonly SpendModel[], override: boolean): SpendModel[] {
    const named = models.filter((m) => m.model !== null)
    return named.length > 1 || (override && named.length > 0) ? named : []
}

/**
 * The share of the By model rows' spend on runs no session has named a model for yet, 0 to 1: the `none` row's cost
 * over every row's. Null when there is no such spend.
 */
export function unattributedShare(rows: readonly ModelRow[]): number | null {
    const total = rows.reduce((sum, m) => sum + (m.cost_usd ?? 0), 0)
    const unnamed = rows.find((m) => m.model === null)?.cost_usd ?? 0
    return unnamed > 0 && total > 0 ? unnamed / total : null
}

/**
 * The By tool table's rows: one kind's as the server sent them, or with no kind each tool summed over every kind, the
 * most characters returned first, its tokens estimated from the sum as the server estimates each kind's.
 */
export function toolRows(tools: readonly SpendTool[], kind: SpendKind | undefined): ToolRow[] {
    if (kind !== undefined) {
        return tools.filter((t) => t.kind === kind)
    }
    // Each row a copy, as By model's are.
    const summed = new Map<string, ToolRow>()
    for (const { kind: _, ...t } of tools) {
        const seen = summed.get(t.tool)
        if (seen === undefined) {
            summed.set(t.tool, t)
        } else {
            seen.runs += t.runs
            seen.calls += t.calls
            seen.errors += t.errors
            seen.result_chars += t.result_chars
            seen.est_tokens = Math.floor(seen.result_chars / CHARS_PER_TOKEN)
        }
    }
    return [...summed.values()].toSorted((a, b) =>
        firstOf(b.result_chars - a.result_chars, a.tool.localeCompare(b.tool)),
    )
}

/** The kinds a filter offers: those with a row in the window, in `canopy spend`'s order, and the one chosen. */
export function kindsOffered(rows: readonly { kind: SpendKind }[], chosen: SpendKind | undefined): SpendKind[] {
    return SPEND_KINDS.filter((k) => k === chosen || rows.some((row) => row.kind === k))
}

// The first of a comparison's differences that is not 0, so each later one only breaks the ties of those before it.
function firstOf(...diffs: number[]): number {
    return diffs.find((d) => d !== 0) ?? 0
}

// Two costs summed, null only when neither reported one.
function addCost(a: number | null | undefined, b: number | null | undefined): number | null {
    return a === null || a === undefined ? (b ?? null) : a + (b ?? 0)
}

/**
 * Where the month stands against its budget: `over` once it spent it, `headed` over when its pace says it will by the
 * month's end, else `under`.
 */
export type BudgetState = 'under' | 'headed' | 'over'

/** Where the month stands against its budget, in words: the spend page's panel and the header's readout say it. */
export const BUDGET_WORD: Record<BudgetState, string> = {
    under: 'On budget',
    headed: 'Headed over',
    over: 'Over budget',
}

/** Where the month stands against its budget. */
export function budgetState(month: SpendMonth): BudgetState {
    if (budgetPercent(month) >= 100) {
        return 'over'
    }
    return month.projected_usd !== null && month.projected_usd > month.budget_usd ? 'headed' : 'under'
}

/**
 * The month's spend over its budget, from 0, as a whole percentage: past 100 once it is over. Floored, so a month short
 * of its budget never reads 100%, and counted in whole cents, so `0.29 * 100` never floors a point away.
 */
export function budgetPercent(month: SpendMonth): number {
    return Math.floor(Math.round((month.spent_usd ?? 0) * 100) / month.budget_usd)
}

/** The alerts a sink hears the month reach, in words: `A sink that takes loop events hears at 50%, 80%, and 100%.` */
export function alertsText(month: SpendMonth): string {
    const percents = new Intl.ListFormat('en-US').format(month.alerts.map((p) => `${p}%`))
    return `A sink that takes loop events hears at ${percents}.`
}

/** The alerts below the budget, which the bar has room to mark: those at or past 100% are past its end. */
export function alertMarks(month: SpendMonth): number[] {
    return month.alerts.filter((p) => p < 100)
}

/** The month in words, `October 2026`, from its `YYYY-MM`, as the operator's calendar names it. */
export function monthName(month: SpendMonth): string {
    const [year, number] = month.month.split('-').map(Number)
    return new Date(year ?? 1970, (number ?? 1) - 1, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
}

/**
 * What the month spent against its budget, and where its pace takes it: `$15.76 of $40 (39%), on pace for $65.14.`
 */
export function budgetText(month: SpendMonth): string {
    const spent = `${costText(month.spent_usd ?? 0)} of $${month.budget_usd} (${budgetPercent(month)}%)`
    const pace = month.projected_usd === null ? '' : `, on pace for ${costText(month.projected_usd)}`
    return `${spent}${pace}.`
}

/**
 * When the runtime's sessions were last read, for the sessions panel's header: `read Oct 8 11:55`, with how the latest
 * read ended when it did not find the record, `read Oct 8 11:55, last failed`; `never read` before the first.
 */
export function sessionsReadText(sessions: SpendSessions, clock: Clock): string {
    if (sessions.read_at === null) {
        return 'never read'
    }
    const read = `read ${stamp(sessions.read_at, clock)}`
    return sessions.status === null || sessions.status === 'found' ? read : `${read}, last ${sessions.status}`
}

/**
 * What the month's spend is made of: `Canopy's runs $12.50, outside canopy $3.26, as of Oct 8 11:55.` Outside canopy is
 * the runtime's sessions none of canopy's runs started, as `canopy loop` last read them, so the time says how fresh it
 * is; before the first read, that it counts none yet.
 */
export function budgetPartsText(month: SpendMonth, clock: Clock): string {
    const runs = `Canopy's runs ${costText(month.runs_usd ?? 0)}`
    if (month.sessions_read_at === null) {
        return `${runs}. Sessions outside canopy count once canopy loop has read them.`
    }
    return `${runs}, outside canopy ${costText(month.outside_usd)}, as of ${stamp(month.sessions_read_at, clock)}.`
}
