// The Connectors page: how each source's runs ended, how long they took, and how fresh each source reads now.
// The numbers are the server's; this lays them out.

import type {
    ConnectorsDay,
    ConnectorsPrevious,
    ConnectorsReport,
    ConnectorsSource,
    ConnectorsSourceRuns,
} from '@/api/types'
import type { DayBar, DayChartSeries } from '@/lib/chart'
import type { Clock } from '@/lib/clock'
import { counted } from '@/lib/descriptions'
import { pickWindow, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { dayLabel, dayName } from '@/lib/spend'

/** The window the page opens on: the week, as the health page does. */
export const DEFAULT_CONNECTORS_WINDOW: ReportWindow = { days: 7 }

/** The windows the page offers, shortest first, the health page's: whole local days. */
export const CONNECTORS_WINDOWS: readonly ReportWindow[] = [DEFAULT_CONNECTORS_WINDOW, { days: 30 }]

/** What a run counts as, as the page says under its runs: what it read, not what changed. */
export const COUNTS_TEXT =
    'A run counts what it read, not what changed: a source that reads everything and finds nothing new is ok. ' +
    "Only a tick's run raises connector_failed on the attention list; a poll between ticks raises nothing, so " +
    'this page counts runs the attention list never showed.'

// The sources' fills by their place, the CI page's checks', written out so Tailwind finds them; past them a neutral.
const SOURCE_FILLS = ['bg-check-1', 'bg-check-2', 'bg-check-3', 'bg-check-4'] as const
const OTHER_FILL = 'bg-check-other'

/** The window the search params name, if the page offers it; undefined for the default. */
export function connectorsWindow(search: { days?: unknown }): ReportWindow | undefined {
    return pickWindow(CONNECTORS_WINDOWS, search)
}

/**
 * The page's description, the window's state, then each stale source by name: `4 of 388 runs read less than asked over
 * 7 days · jira stale`, or `no source ran over 7 days`.
 */
export function connectorsLine(found: Pick<ConnectorsReport, 'days' | 'runs' | 'sources'>): string {
    const figures = connectorsFigures(found)
    const over = windowName(found)
    const head =
        figures.runs === 0
            ? `no source ran over ${over}`
            : `${figures.short} of ${runsText(figures.runs)} read less than asked over ${over}`
    const stale = found.sources.filter((s) => s.stale).map((s) => `${s.name} stale`)
    return [head, ...stale].join(' · ')
}

// A count of runs with its thousands grouped, since a week of polls runs to thousands: `4,210 runs`.
function runsText(n: number): string {
    return n === 1 ? '1 run' : `${n.toLocaleString('en-US')} runs`
}

/** The window's headline figures, as the page's tiles show them. */
export interface ConnectorsFigures {
    /** The runs of every source. */
    runs: number
    /** Of those, the ones that read less than they were asked. */
    short: number
    /** Their share of the runs; null with none. */
    rate: number | null
    /** The lines canopy refused. */
    refused: number
}

/** The window's runs, how many read less than asked and their share, and the lines refused, over every source. */
export function connectorsFigures(found: Pick<ConnectorsReport, 'runs'>): ConnectorsFigures {
    const runs = found.runs.reduce((sum, s) => sum + s.runs, 0)
    const short = found.runs.reduce((sum, s) => sum + shortRuns(s), 0)
    const refused = found.runs.reduce((sum, s) => sum + lineSum(s.refused), 0)
    return { runs, short, rate: runs === 0 ? null : short / runs, refused }
}

/** The window before's headline figures, as `connectorsFigures` reads the window's. */
export function previousConnectorsFigures(previous: ConnectorsPrevious): ConnectorsFigures {
    return {
        runs: previous.runs,
        short: previous.short,
        rate: previous.runs === 0 ? null : previous.short / previous.runs,
        refused: previous.refused,
    }
}

/** A source's runs that read less than they were asked: `partial` and `failed` together. */
export function shortRuns(source: Pick<ConnectorsSourceRuns, 'partial' | 'failed'>): number {
    return source.partial + source.failed
}

/** A source's runs that read less than asked as a share of its runs: `2%`, `<1%` for a few in many, `0%` for none. */
export function shortShareText(source: Pick<ConnectorsSourceRuns, 'runs' | 'partial' | 'failed'>): string {
    const short = shortRuns(source)
    if (source.runs === 0 || short === 0) {
        return source.runs === 0 ? '–' : '0%'
    }
    const percent = (short / source.runs) * 100
    return percent < 1 ? '<1%' : `${Math.round(percent)}%`
}

/** Lines by kind, summed. */
export function lineSum(lines: Record<string, number>): number {
    return Object.values(lines).reduce((sum, n) => sum + n, 0)
}

/** Lines by kind in words, the most first, then by name: `1164 ticket, 195 comment`, or a dash for none. */
export function linesText(lines: Record<string, number>): string {
    const kinds = Object.entries(lines)
        .filter(([, n]) => n > 0)
        .toSorted(([a, m], [b, n]) => (n === m ? a.localeCompare(b) : n - m))
    return kinds.length === 0 ? '–' : kinds.map(([kind, n]) => `${n} ${kind}`).join(', ')
}

/**
 * The by-day chart's series, a source each in the order the report gives them, the order a tick runs them, in the CI
 * page's fills by place. A series' key is its place, `source-0`, since a source's name is the operator's.
 */
export function connectorSeries(runs: readonly Pick<ConnectorsSourceRuns, 'source' | 'kind'>[]): DayChartSeries[] {
    return runs.map((s, i) => ({
        key: `source-${i}`,
        label: s.source,
        hint: `The ${s.source} source's runs (${s.kind}) that read less than asked`,
        fill: SOURCE_FILLS[i] ?? OTHER_FILL,
    }))
}

/** A day's runs that read less than asked, over every source. */
export function shortSum(day: Pick<ConnectorsDay, 'short'>): number {
    return day.short.reduce((sum, n) => sum + n, 0)
}

/**
 * A day's bar on hover: its date, its runs that read less than asked, and each source's, by the legend's names:
 * `Oct 7: 2 read less than asked, jira 1, github 1`.
 */
export function connectorDayHint(day: ConnectorsDay, series: readonly DayChartSeries[], clock: Clock): string {
    const head = `${dayName(day, clock)}: ${shortSum(day)} read less than asked`
    const named = series.flatMap((s, i) => {
        const n = day.short[i] ?? 0
        return n > 0 ? [`${s.label} ${n}`] : []
    })
    return named.length === 0 ? head : `${head}, ${named.join(', ')}`
}

/** Each day as the chart draws it: its runs that read less than asked, by source bottom up. */
export function connectorBars(
    days: readonly ConnectorsDay[],
    series: readonly DayChartSeries[],
    clock: Clock,
): DayBar[] {
    return days.map((day) => {
        const total = shortSum(day)
        return {
            key: day.day,
            label: dayLabel(day, clock),
            hint: connectorDayHint(day, series, clock),
            total,
            totalText: String(total),
            segments: series.map((s, i) => ({ key: s.key, fill: s.fill, value: day.short[i] ?? 0 })),
        }
    })
}

/**
 * How fresh a source reads, as `canopy status` says it after its latest run: `feed through change 41`, `2 never
 * observed`, or nothing to add; the age of its oldest observation is the page's to write, as a time.
 */
export function freshnessText(source: Pick<ConnectorsSource, 'never' | 'through' | 'oldest_at'>): string {
    if (source.through !== null) {
        return source.oldest_at === null
            ? `feed through change ${source.through}, never read to its end`
            : `feed through change ${source.through}`
    }
    if (source.never > 0) {
        return `${source.never} never observed`
    }
    return source.oldest_at === null ? 'nothing observed' : ''
}

/**
 * What the page cannot see, as it says under the runs: how long the journal keeps a run, so a window that reaches past
 * it is not whole. `retention.journal_days` at 0 keeps every run.
 */
export function retentionText(found: Pick<ConnectorsReport, 'journal_days' | 'days'>): string {
    if (found.journal_days === 0) {
        return 'retention.journal_days is 0, so the journal keeps every run.'
    }
    const kept =
        `The journal keeps a run ${counted(found.journal_days, 'day')} (retention.journal_days), ` +
        "each source's newest whatever its age"
    return found.days > found.journal_days ? `${kept}, so this window is not whole.` : `${kept}.`
}
