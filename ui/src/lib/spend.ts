// The spend page (ROADMAP M33): what each UTC day cost, by kind, and what the overseer's ticks bought. The numbers
// are the server's (`canopy spend`); this lays them out.

import type { SpendCosts, SpendDay, SpendGroup } from '@/api/types'
import { costText } from '@/lib/cost-total'

/** The windows the page offers, in days. The first is the default, as it is `canopy spend`'s. */
export const SPEND_WINDOWS = [7, 30] as const

/** A window the page offers, in days. */
export type SpendWindowDays = (typeof SPEND_WINDOWS)[number]

/** A series of the by-day chart: a part of a day's spend no other series counts. */
export type SeriesKey = 'idle' | 'overseer' | 'workers' | 'chores' | 'reviews' | 'dry_run'

/** One series: what it counts, its name in the legend, and its fill, written out so Tailwind finds it. */
export interface Series {
    /** What it counts. `overseer` is the live overseer's spend that idle ticks did not make. */
    key: SeriesKey
    /** Its name in the legend and the table. */
    label: string
    /** Its fill: a spend token, never a state's color. */
    fill: string
}

/**
 * The series bottom up. Idle ticks first, on the baseline, so their spend compares across days; the rest of the
 * overseer's on it, a deeper shade of the same hue; then the runs the overseer started, then dry runs.
 */
export const SERIES: readonly Series[] = [
    { key: 'idle', label: 'idle ticks', fill: 'bg-spend-idle' },
    { key: 'overseer', label: 'other ticks', fill: 'bg-spend-overseer' },
    { key: 'workers', label: 'workers and splits', fill: 'bg-spend-workers' },
    { key: 'chores', label: 'chores', fill: 'bg-spend-chores' },
    { key: 'reviews', label: 'reviews', fill: 'bg-spend-reviews' },
    { key: 'dry_run', label: 'dry runs', fill: 'bg-spend-dry-run' },
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
    idle: 'The loop found nothing new: it decided only waits and skips, and nothing reached the journal before it',
    busy: 'The loop ran it and it was not idle: something changed or it acted',
    hand_run: 'canopy tick, run by hand: no loop said whether it was idle',
    not_ok: 'It ended other than ok: skipped, failed, or abandoned',
    dry_run: 'A dry run: it planned and acted on nothing',
}

/** The validated window of a search param: one the page offers, or undefined for the default. */
export function spendWindow(value: unknown): SpendWindowDays | undefined {
    return SPEND_WINDOWS.find((days) => days === value || String(days) === value)
}

/** A day's cost in one series: idle ticks' part taken out of the overseer's, so no dollar is counted twice. */
export function seriesCost(costs: SpendCosts, key: SeriesKey): number {
    if (key === 'overseer') {
        return Math.max(0, (costs.overseer ?? 0) - (costs.idle ?? 0))
    }
    return costs[key] ?? 0
}

/** The tallest day's total, the chart's top; 0 when nothing in the window reported a cost. */
export function chartTop(days: SpendDay[]): number {
    return Math.max(0, ...days.map((day) => day.costs.total ?? 0))
}

/** A day's bar on hover: its date, its total, and each series it has, in the chart's order. */
export function dayHint(day: SpendDay): string {
    const parts = SERIES.map((series) => [series.label, seriesCost(day.costs, series.key)] as const)
        .filter(([, usd]) => usd > 0)
        .map(([label, usd]) => `${label} ${costText(usd)}`)
    const total = day.costs.total === null ? 'nothing reported' : costText(day.costs.total)
    return parts.length === 0 ? `${dayLabel(day.day)}: ${total}` : `${dayLabel(day.day)}: ${total}, ${parts.join(', ')}`
}

/** A UTC day, `2026-10-07`, as the chart's axis says it: `Oct 7`. */
export function dayLabel(day: string): string {
    const [year, month, date] = day.split('-').map(Number)
    return new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1, date ?? 1)).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        timeZone: 'UTC',
    })
}

/**
 * Whether the axis names the day at `index` of `count`: every day of a week, and of a month every fifth back from
 * the last, so today is always named and the labels never crowd.
 */
export function axisNames(index: number, count: number): boolean {
    return count <= SPEND_WINDOWS[0] || (count - 1 - index) % 5 === 0
}

/** A share, 0 to 1, as a whole percent: `41%`, or a dash when there is none. */
export function shareText(share: number | null): string {
    return share === null ? '–' : `${Math.round(share * 100)}%`
}
