// The health page (canopy health): how the last days' runs ended, the newest failures, and what the guards refused.
// The numbers are the server's; this lays them out.

import type { HealthCounts, HealthDay, HealthReport, SpendKind } from '@/api/types'
import type { DayBar, DayChartSeries } from '@/lib/chart'
import type { Clock } from '@/lib/clock'
import { counted } from '@/lib/descriptions'
import { pickWindow, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { dayLabel, dayName } from '@/lib/spend'

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
