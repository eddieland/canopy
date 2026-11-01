// The health page (canopy health): how the last days' runs ended, the newest failures, and what the guards refused.
// The numbers are the server's; this lays them out.

import type {
    HealthBins,
    HealthCounts,
    HealthDay,
    HealthDuration,
    HealthOutcome,
    HealthPrevious,
    HealthReport,
    SpendKind,
} from '@/api/types'
import type { DayBar, DayChartSeries } from '@/lib/chart'
import type { Clock } from '@/lib/clock'
import { counted } from '@/lib/descriptions'
import { pickWindow, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { hoursText } from '@/lib/reports'
import { dayLabel, dayName, shareText } from '@/lib/spend'

/** The window the page opens on, as `canopy health` does: the week. */
export const DEFAULT_HEALTH_WINDOW: ReportWindow = { days: 7 }

/** The windows the page offers, shortest first: whole local days, as `canopy health --days` reads. */
export const HEALTH_WINDOWS: readonly ReportWindow[] = [DEFAULT_HEALTH_WINDOW, { days: 30 }]

/** A series of the failures chart: one kind of run, in the spend series' fill for it, so a kind is one color. */
export interface HealthSeries extends DayChartSeries {
    /** The kind it counts. */
    key: SpendKind
}

/** The kinds bottom up, in the order `canopy health` lists them, each in its spend series' fill. */
export const HEALTH_SERIES: readonly HealthSeries[] = [
    { key: 'overseer', label: 'overseer', hint: "The overseer's ticks, dry runs included", fill: 'bg-spend-overseer' },
    { key: 'workers', label: 'workers', hint: 'The worker runs the overseer started', fill: 'bg-spend-workers' },
    { key: 'plans', label: 'plans', hint: "The plan runs that wrote tickets' plans", fill: 'bg-spend-plans' },
    { key: 'chores', label: 'chores', hint: 'The chores canopy ran, your tries included', fill: 'bg-spend-chores' },
    { key: 'reviews', label: 'reviews', hint: "canopy's reviews of PRs", fill: 'bg-spend-reviews' },
    { key: 'tasks', label: 'tasks', hint: 'The runs of the one-off tasks you submitted', fill: 'bg-spend-tasks' },
]

/** The window the search params name, if the page offers it; undefined for the default. */
export function healthWindow(search: { days?: unknown }): ReportWindow | undefined {
    return pickWindow(HEALTH_WINDOWS, search)
}

/** A count over every kind. */
export function countSum(counts: HealthCounts): number {
    return HEALTH_SERIES.reduce((sum, series) => sum + counts[series.key], 0)
}

/**
 * The page's description, the window's state: `3 of 140 runs failed over 7 days`, or, with none ended,
 * `no run ended over 7 days`.
 */
export function healthLine(found: Pick<HealthReport, 'days' | 'per_day'>): string {
    const ended = found.per_day.reduce((sum, day) => sum + countSum(day.ended), 0)
    const failed = found.per_day.reduce((sum, day) => sum + countSum(day.failed), 0)
    const over = windowName(found)
    return ended === 0 ? `no run ended over ${over}` : `${failed} of ${counted(ended, 'run')} failed over ${over}`
}

/** The window's headline figures, as the page's tiles show them. */
export interface HealthFigures {
    /** The runs that ended. */
    runs: number
    /** Of those, the runs that failed. */
    failed: number
    /** The failed runs' share of the ended ones; null with none ended. */
    rate: number | null
    /** What the failed runs cost, in US dollars; null when none of them reported a cost. */
    failedUsd: number | null
}

/** The window's runs, its failures, their share, and what they cost, over every kind. */
export function healthFigures(found: Pick<HealthReport, 'per_day' | 'outcomes'>): HealthFigures {
    const runs = found.per_day.reduce((sum, day) => sum + countSum(day.ended), 0)
    const failed = found.per_day.reduce((sum, day) => sum + countSum(day.failed), 0)
    const costs = found.outcomes.filter((o) => o.failed).map((o) => o.cost_usd ?? null)
    const priced = costs.filter((usd) => usd !== null)
    return {
        runs,
        failed,
        rate: runs === 0 ? null : failed / runs,
        failedUsd: priced.length === 0 ? null : priced.reduce((sum, usd) => sum + usd, 0),
    }
}

/** The window before's headline figures, as `healthFigures` reads the window's. */
export function previousHealthFigures(previous: HealthPrevious): HealthFigures {
    return {
        runs: previous.runs_ended,
        failed: previous.failed,
        rate: previous.runs_ended === 0 ? null : previous.failed / previous.runs_ended,
        failedUsd: previous.failed_cost_usd,
    }
}

/**
 * A day's bar on hover: its date, its failed and ended runs, and each kind that failed, by the legend's names:
 * `Oct 7: 3 failed of 12 ended, overseer 1, workers 2`.
 */
export function healthDayHint(day: HealthDay, clock: Clock): string {
    const failed = countSum(day.failed)
    const head = `${dayName(day, clock)}: ${failed} failed of ${countSum(day.ended)} ended`
    const kinds = HEALTH_SERIES.filter((s) => day.failed[s.key] > 0).map((s) => `${s.label} ${day.failed[s.key]}`)
    return kinds.length === 0 ? head : `${head}, ${kinds.join(', ')}`
}

/** Each day as the failures chart draws it: its failed runs, by kind bottom up. */
export function healthBars(days: readonly HealthDay[], clock: Clock): DayBar[] {
    return days.map((day) => {
        const total = countSum(day.failed)
        return {
            key: day.day,
            label: dayLabel(day, clock),
            hint: healthDayHint(day, clock),
            total,
            totalText: String(total),
            segments: HEALTH_SERIES.map((s) => ({ key: s.key, fill: s.fill, value: day.failed[s.key] })),
        }
    })
}

/** A day's failed runs' share of its ended ones, as the failures table's rate column shows it: `25%`, or a dash. */
export function dayRateText(day: HealthDay): string {
    const ended = countSum(day.ended)
    return shareText(ended === 0 ? null : countSum(day.failed) / ended)
}

/** How many of one sort's runs ended in one status, as a chip on its row says it. */
export interface OutcomeStatus {
    /** How they ended, as the journal records it. */
    status: string
    /** Whether that is a failed ending for the kind. */
    failed: boolean
    /** How many ended so. */
    runs: number
}

/** One sort of a kind's runs, a row of the outcomes tree: its runs, what they cost, and how they ended. */
export interface OutcomeSort {
    /** The sort, as `HealthOutcome.what`. */
    what: string
    /** Its ended runs. */
    runs: number
    /** What they cost, in US dollars; null when none reported a cost. */
    costUsd: number | null
    /** Each way they ended, the most runs first. */
    statuses: OutcomeStatus[]
}

/** One kind's runs, a group of the outcomes tree: its runs, its failures, what they cost, and its sorts. */
export interface OutcomeKind {
    /** The kind of run. */
    kind: SpendKind
    /** Its ended runs. */
    runs: number
    /** Of those, the ones that failed. */
    failed: number
    /** What its runs cost, in US dollars; null when none reported a cost. */
    costUsd: number | null
    /** Its sorts, in the report's order. */
    sorts: OutcomeSort[]
}

/**
 * The report's outcomes as a tree, a kind over its sorts over their statuses, each with its runs and what they cost,
 * in the report's order of kinds and sorts: the shape `canopy health` prints flat.
 */
export function outcomeTree(outcomes: readonly HealthOutcome[]): OutcomeKind[] {
    const kinds: OutcomeKind[] = []
    for (const o of outcomes) {
        let kind = kinds.at(-1)
        if (kind?.kind !== o.kind) {
            kind = { kind: o.kind, runs: 0, failed: 0, costUsd: null, sorts: [] }
            kinds.push(kind)
        }
        let sort = kind.sorts.find((s) => s.what === o.what)
        if (sort === undefined) {
            sort = { what: o.what, runs: 0, costUsd: null, statuses: [] }
            kind.sorts.push(sort)
        }
        sort.statuses.push({ status: o.status, failed: o.failed, runs: o.runs })
        sort.runs += o.runs
        sort.costUsd = addUsd(sort.costUsd, o.cost_usd ?? null)
        kind.runs += o.runs
        kind.failed += o.failed ? o.runs : 0
        kind.costUsd = addUsd(kind.costUsd, o.cost_usd ?? null)
    }
    for (const sort of kinds.flatMap((k) => k.sorts)) {
        sort.statuses.sort((a, b) => b.runs - a.runs)
    }
    return kinds
}

/** One band of a sort's runs by their length's share of its timeout, as the durations bar draws it. */
export interface DurationBand extends DayChartSeries {
    /** The band it counts. */
    key: keyof HealthBins
}

/**
 * The bands of a run's length against its timeout, the quickest first: the Reviews page's ramp of waits, lightest
 * quickest, and at the limit or past it in the failed state's color, since a run that long was stopped.
 */
export const DURATION_BANDS: readonly DurationBand[] = [
    { key: 'under_quarter', label: 'under 25%', hint: 'Under a quarter of its timeout', fill: 'bg-wait-1' },
    { key: 'under_half', label: '25–50%', hint: 'From a quarter of its timeout to under half', fill: 'bg-wait-2' },
    {
        key: 'under_three_quarters',
        label: '50–75%',
        hint: 'From half its timeout to under three quarters',
        fill: 'bg-wait-3',
    },
    { key: 'under_limit', label: '75–100%', hint: 'From three quarters to under the timeout', fill: 'bg-wait-4' },
    { key: 'over_limit', label: 'at the limit', hint: 'At its timeout or past it', fill: 'bg-status-failed' },
]

/**
 * A sort's runs by band in words, for a screen reader and the bar's tip: `2 under 25%, 1 at 50–75%, 1 at the limit`,
 * each band its share of the timeout.
 */
export function binsText(bins: HealthBins): string {
    return DURATION_BANDS.filter((b) => bins[b.key] > 0)
        .map((b) => `${bins[b.key]} ${b.label.startsWith('at ') || b.key === 'under_quarter' ? '' : 'at '}${b.label}`)
        .join(', ')
}

/** A run's length as a readout: `40s` under a minute, `4.5m` under ten, `27m` under an hour, `1.2h` past it. */
export function minutesText(minutes: number): string {
    if (minutes < 1) {
        return `${Math.round(minutes * 60)}s`
    }
    if (minutes < 10) {
        return `${minutes.toFixed(1)}m`
    }
    return minutes < 60 ? `${Math.round(minutes)}m` : hoursText(minutes / 60)
}

/**
 * Whether a sort's median run takes three quarters of its timeout or more: one to give more time or less work. False
 * with no timeout to hold it to.
 */
export function nearLimit(duration: Pick<HealthDuration, 'median_minutes' | 'limit_minutes'>): boolean {
    const limit = duration.limit_minutes ?? null
    return limit !== null && limit > 0 && duration.median_minutes >= 0.75 * limit
}

/** The report's durations by kind, in its order: each kind's sorts under it. */
export function durationsByKind(durations: readonly HealthDuration[]): { kind: SpendKind; sorts: HealthDuration[] }[] {
    const kinds: { kind: SpendKind; sorts: HealthDuration[] }[] = []
    for (const d of durations) {
        const last = kinds.at(-1)
        if (last?.kind === d.kind) {
            last.sorts.push(d)
        } else {
            kinds.push({ kind: d.kind, sorts: [d] })
        }
    }
    return kinds
}

// A sum of costs that keeps a cost nothing reported apart from a cost of nothing.
function addUsd(sum: number | null, usd: number | null): number | null {
    return usd === null ? sum : (sum ?? 0) + usd
}
