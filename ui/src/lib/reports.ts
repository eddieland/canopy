// The reports page: what each local calendar month cost, in dollars and tokens, and what it got done. The numbers are
// the server's (`canopy.serve.monthly`); this lays them out.

import type { ReportMonth, ReportTicket, ReportTokens } from '@/api/types'
import type { DayBar, DayChartSeries } from '@/lib/chart'
import type { Clock } from '@/lib/clock'
import { costText } from '@/lib/cost-total'
import { counted } from '@/lib/descriptions'
import { SERIES, shareText } from '@/lib/spend'
import { stamp } from '@/lib/time'

/**
 * How many months the page reads with no span picked: a year, of which it opens on those from the first that holds
 * anything (`fittedMonths`).
 */
export const DEFAULT_MONTHS = 12

/** The spans the page offers, in months, shortest first: each draws every month of it, the empty ones too. */
export const REPORT_SPANS: readonly number[] = [6, DEFAULT_MONTHS, 24]

/** The span the search's `months` names, if the page offers it; undefined for none, which fits the journal. */
export function reportSpan(value: unknown): number | undefined {
    return REPORT_SPANS.find((n) => n === value || String(n) === value)
}

/**
 * The months the page opens on with no span picked: those from the first that holds anything, so a young workspace
 * draws no year of empty months before it; the latest alone when none holds anything, so the page names the month it
 * is in.
 */
export function fittedMonths(months: readonly ReportMonth[]): readonly ReportMonth[] {
    const first = months.findIndex((month) => holdsAnything(month))
    return first === -1 ? months.slice(-1) : months.slice(first)
}

/** Where a fitted span starts, in the month chart's header: `since April 2026`. Empty with no month read. */
export function sinceText(months: readonly ReportMonth[]): string {
    const [first] = months
    return first === undefined ? '' : `since ${monthLabel(first.month, 'long')}`
}

// Whether a month holds anything to report: a run, a cost, a ticket landed or closed, a PR, a PR head checked, a first
// review, a session outside canopy.
function holdsAnything(month: ReportMonth): boolean {
    return (
        month.runs > 0 ||
        month.cost_usd !== null ||
        month.landed.length > 0 ||
        month.closed > 0 ||
        month.pull_requests > 0 ||
        month.heads > 0 ||
        month.first_reviews > 0 ||
        month.outside.sessions > 0
    )
}

/**
 * The month chart's series bottom up, as the spend chart names them: each kind of canopy's runs, in the spend series'
 * fills, then the sessions outside canopy on top, as no part of canopy's work. Idle ticks and dry runs are no kind of
 * the month's, which counts them in the overseer's.
 */
export const MONTH_SERIES: readonly DayChartSeries[] = SERIES.filter((s) => s.key !== 'idle' && s.key !== 'dry_run')

/**
 * Each month as the month chart draws it: the spend chart at a month's pitch, a bar of what it cost stacked by kind,
 * the sessions outside canopy on top, named on the axis `Oct 2026` and on hover with each series it has.
 */
export function monthBars(months: readonly ReportMonth[]): DayBar[] {
    return months.map((m) => {
        const segments = MONTH_SERIES.map((series) => ({
            key: series.key,
            fill: series.fill,
            value: series.key === 'outside' ? (m.outside.cost_usd ?? 0) : kindCost(m, series.key),
        }))
        const parts = segments
            .filter((segment) => segment.value > 0)
            .map((segment) => `${MONTH_SERIES.find((s) => s.key === segment.key)?.label} ${costText(segment.value)}`)
        const name = monthLabel(m.month, 'long')
        const total = m.cost_usd === null ? 'nothing reported' : costText(m.cost_usd)
        return {
            key: m.month,
            label: monthLabel(m.month),
            hint: parts.length === 0 ? `${name}: ${total}` : `${name}: ${total}, ${parts.join(', ')}`,
            total: m.cost_usd ?? 0,
            totalText: costText(m.cost_usd),
            segments,
        }
    })
}

// What one kind of the month's runs cost; 0 when it has none or reported none.
function kindCost(month: ReportMonth, kind: string): number {
    return month.kinds.find((k) => k.kind === kind)?.cost_usd ?? 0
}

/**
 * How a month's cost moved on the month before's, on its cell's hover: `+$1.77 on September 2026`. Undefined for the
 * first month of the span, or when either reported no cost.
 */
export function monthChange(
    now: number | null,
    before: ReportMonth | undefined,
    of: (month: ReportMonth) => number | null,
): string | undefined {
    const was = before === undefined ? null : of(before)
    if (before === undefined || now === null || was === null) {
        return undefined
    }
    // Written as a cost is (readout-delta's `usdChange`, which imports this module): a cent's float noise is no move.
    const name = monthLabel(before.month, 'long')
    const change = now - was
    const size = costText(Math.abs(change))
    return size === costText(0) ? `same as ${name}` : `${change > 0 ? '+' : '−'}${size} on ${name}`
}

/** A month's failed runs in its table's cell, as the Health page counts them: `3`; a dash when no run ended. */
export function failedText(month: ReportMonth): string {
    return month.runs_ended === 0 ? '–' : String(month.failed)
}

/**
 * What a month's failed cell counts, on its hover: `3 of 46 runs failed, 7%, costing $1.20`. Undefined when no run
 * ended.
 */
export function failedHint(month: ReportMonth): string | undefined {
    if (month.runs_ended === 0) {
        return undefined
    }
    const share = shareText(month.failed / month.runs_ended)
    const said = `${month.failed} of ${counted(month.runs_ended, 'run')} failed, ${share}`
    return month.failed_cost_usd === null ? said : `${said}, costing ${costText(month.failed_cost_usd)}`
}

/** A month's share of PR heads green first time, as the CI page reads it: `71%`; a dash when no head was checked. */
export function greenFirstText(month: ReportMonth): string {
    return month.heads === 0 ? '–' : shareText(month.green_first / month.heads)
}

/** What a month's green-first cell counts, on its hover: `10 of 14 PR heads`. Undefined when no head was checked. */
export function greenFirstHint(month: ReportMonth): string | undefined {
    return month.heads === 0 ? undefined : `${month.green_first} of ${counted(month.heads, 'PR head')}`
}

/**
 * A row's share of the month, as its bar on the reports page draws it and its hover says it, 0 to 100: `cost` over
 * `whole`, the month's; 0 when either is nothing.
 */
export function monthShare(cost: number | null, whole: number | null): number {
    return cost === null || whole === null || whole <= 0 ? 0 : Math.min(100, (cost / whole) * 100)
}

/** One of Delivery's medians drawn across the months: what it is, how to read a month's, and its figure in words. */
export interface DeliveryTrend {
    /** Its test ids' end. */
    key: string
    /** Its name, as the table's column names it. */
    label: string
    /** A month's median of it; null with none. */
    value: (month: ReportMonth) => number | null
    /** A median in words, as its column writes it: `2.5`, `20.8h`. */
    text: (value: number | null) => string
    /** Which of the month's figures ran on GitHub's clock, for a time (`clockShare`); undefined for a count. */
    clock?: 'to land' | 'review wait'
    /** How many figures a month's median is of, when they are not its landed tickets: `3 first reviews`. */
    of?: (month: ReportMonth) => string
}

/**
 * Delivery's medians, in the table's order, each drawn across the months over it: four per landed ticket, then the
 * first reviews', of every PR reviewed first in the month, landed or not, as the Reviews page times them.
 */
export const DELIVERY_TRENDS: readonly DeliveryTrend[] = [
    { key: 'iterations', label: 'iterations', value: (m) => m.median_iterations, text: medianText },
    { key: 'comments', label: 'PR comments', value: (m) => m.median_pr_comments, text: medianText },
    { key: 'to-land', label: 'to land', value: (m) => m.median_hours_to_land, text: hoursText, clock: 'to land' },
    {
        key: 'review-wait',
        label: 'review wait',
        value: (m) => m.median_review_wait_hours,
        text: hoursText,
        clock: 'review wait',
    },
    {
        key: 'first-review',
        label: 'first review',
        value: (m) => m.median_first_review_hours ?? null,
        text: hoursText,
        of: (m) => counted(m.first_reviews, 'first review'),
    },
]

/**
 * A month's point on a Delivery trend, on hover: `Oct 2026: 20.8h`, then, for a time, how many of its figures ran on
 * GitHub's clock (`clockShare`): `Oct 2026: 20.8h · 2 of 3 from GitHub's times, the rest from proxies`; or, for a
 * median of other figures than the landed tickets', how many: `Oct 2026: 4.0h · 3 first reviews`.
 */
export function trendPointHint(month: ReportMonth, trend: DeliveryTrend): string {
    const said = `${monthLabel(month.month)}: ${trend.text(trend.value(month))}`
    const more = trend.clock === undefined ? trend.of?.(month) : clockShare(month, trend.clock)
    return more === undefined ? said : `${said} · ${more}`
}

/** The month the search's `month` names, `YYYY-MM`, if it is one; undefined otherwise. */
export function reportMonth(value: unknown): string | undefined {
    return typeof value === 'string' && /^\d{4}-(0[1-9]|1[0-2])$/u.test(value) ? value : undefined
}

/** The month shown in detail: the one `chosen` names, if the report holds it, else the latest. */
export function pickedMonth(months: readonly ReportMonth[], chosen: string | undefined): ReportMonth | undefined {
    return months.find((m) => m.month === chosen) ?? months.at(-1)
}

/** A month's `YYYY-MM` in words, short, `Oct 2026`, or long, `October 2026`, as the operator's calendar names it. */
export function monthLabel(month: string, length: 'short' | 'long' = 'short'): string {
    const [year, number] = month.split('-').map(Number)
    return new Date(year ?? 1970, (number ?? 1) - 1, 1).toLocaleDateString('en-US', { month: length, year: 'numeric' })
}

/**
 * The page's description, the latest month at a glance, beside what the month before cost:
 * `$412.30 in October 2026 · 7 tickets landed · 9 PRs · $380.12 in September`, the month before named with its year
 * only when that is another. Empty with no month read.
 */
export function reportLine(months: readonly ReportMonth[]): string {
    const latest = months.at(-1)
    if (latest === undefined) {
        return ''
    }
    const spent = `${costText(latest.cost_usd)} in ${monthLabel(latest.month, 'long')}`
    const line = `${spent} · ${counted(latest.landed.length, 'ticket')} landed · ${counted(latest.pull_requests, 'PR')}`
    const before = months.at(-2)
    if (before === undefined) {
        return line
    }
    const sameYear = before.month.slice(0, 4) === latest.month.slice(0, 4)
    const name = sameYear ? monthLabel(before.month, 'long').replace(/ \d{4}$/u, '') : monthLabel(before.month, 'long')
    return `${line} · ${costText(before.cost_usd)} in ${name}`
}

/**
 * What the month's row of the sessions outside canopy counts, on its name's hover: the runtime's sessions none of
 * canopy's runs started, as of `canopy loop`'s last read of them, or that it has read none yet.
 */
export function outsideHint(readAt: string | null, clock: Clock): string {
    const what = "The runtime's sessions none of canopy's runs started, yours among them, counted in sessions, not runs"
    return readAt === null
        ? `${what}. canopy loop has not read them yet, so none is counted.`
        : `${what}, as of ${stamp(readAt, clock)}.`
}

/** What the model calls were sent, read from the cache or not, as the transcript counts a call's `sent`. */
export function sentTokens(tokens: ReportTokens): number {
    return tokens.input + tokens.cache_read + tokens.cache_write
}

/** What the models wrote, reasoning included. */
export function wroteTokens(tokens: ReportTokens): number {
    return tokens.output + tokens.reasoning
}

/** A span in hours as a readout: `45m` under an hour, `5.2h` under two days, `3.1d` past them; a dash for none. */
export function hoursText(hours: number | null): string {
    if (hours === null) {
        return '–'
    }
    if (hours < 1) {
        return `${Math.round(hours * 60)}m`
    }
    return hours < 48 ? `${hours.toFixed(1)}h` : `${(hours / 24).toFixed(1)}d`
}

/** A median count as a readout, whole when it is one: `3`, `2.5`; a dash for none. */
export function medianText(n: number | null): string {
    if (n === null) {
        return '–'
    }
    return Number.isInteger(n) ? String(n) : n.toFixed(1)
}

/**
 * Which clock a landed ticket's time to land ran on, on its figure's hover: GitHub's merge time, or the tick that
 * marked it done standing in where canopy kept none. Undefined with no figure.
 */
export function toLandHint(ticket: ReportTicket): string | undefined {
    if (ticket.hours_to_land === null) {
        return undefined
    }
    return ticket.merged_at === null
        ? 'To the tick that marked it done: canopy kept no merge time from GitHub for its PR'
        : "To its PR's merge, as GitHub timed it"
}

/**
 * Which clock a landed ticket's review wait ran on, on its figure's hover: GitHub's, from the first review asked for
 * once its PR was ready, or from ready; or its first worker run that ended done standing in. Undefined with no figure.
 */
export function reviewWaitHint(ticket: ReportTicket): string | undefined {
    if (ticket.review_wait_hours === null) {
        return undefined
    }
    return ticket.awaiting_review_at === null
        ? 'From the end of its first worker run that ended done: canopy kept no ready time from GitHub for its PR'
        : GITHUB_WAIT_HINT
}

/** Where a review wait on GitHub's clock starts. */
const GITHUB_WAIT_HINT =
    'From when its PR began waiting on a review, as GitHub timed it: the first review asked for once it was ready, ' +
    'or when it was ready'

/**
 * How many of a month's medians' figures ran on GitHub's clock, on the median's hover: `2 of 3 from GitHub's times,
 * the rest from proxies`. Undefined when no ticket has the figure.
 */
export function clockShare(month: ReportMonth, figure: 'to land' | 'review wait'): string | undefined {
    const known =
        figure === 'to land'
            ? month.landed.filter((t) => t.hours_to_land !== null)
            : month.landed.filter((t) => t.review_wait_hours !== null)
    if (known.length === 0) {
        return undefined
    }
    const github = known.filter((t) => (figure === 'to land' ? t.merged_at : t.awaiting_review_at) !== null).length
    if (github === known.length) {
        return known.length === 1 ? "From GitHub's times" : `All ${known.length} from GitHub's times`
    }
    if (github === 0) {
        return known.length === 1 ? 'From a proxy: canopy kept no time from GitHub' : `All ${known.length} from proxies`
    }
    return `${github} of ${known.length} from GitHub's times, the rest from proxies`
}
