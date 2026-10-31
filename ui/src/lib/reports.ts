// The reports page: what each local calendar month cost, in dollars and tokens, and what it got done. The numbers are
// the server's (`canopy.serve.monthly`); this lays them out.

import type { ReportMonth, ReportTicket, ReportTokens } from '@/api/types'
import type { Clock } from '@/lib/clock'
import { costText } from '@/lib/cost-total'
import { counted } from '@/lib/descriptions'
import { stamp } from '@/lib/time'

/** How many months the page opens on: a year. */
export const DEFAULT_MONTHS = 12

/** The spans the page offers, in months, shortest first. */
export const REPORT_SPANS: readonly number[] = [6, DEFAULT_MONTHS, 24]

/** The span the search's `months` names, if the page offers it; undefined for the default. */
export function reportSpan(value: unknown): number | undefined {
    return REPORT_SPANS.find((n) => n !== DEFAULT_MONTHS && (n === value || String(n) === value))
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
 * The page's description, the latest month at a glance: `$412.30 in October 2026 · 7 tickets landed · 9 PRs`. Empty
 * with no month read.
 */
export function reportLine(months: readonly ReportMonth[]): string {
    const latest = months.at(-1)
    if (latest === undefined) {
        return ''
    }
    const spent = `${costText(latest.cost_usd)} in ${monthLabel(latest.month, 'long')}`
    return `${spent} · ${counted(latest.landed.length, 'ticket')} landed · ${counted(latest.pull_requests, 'PR')}`
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

/** A month's cost as a share of the dearest month's, 0 to 100, for its bar; 0 when nothing cost anything. */
export function costPercent(month: ReportMonth, months: readonly ReportMonth[]): number {
    const top = Math.max(0, ...months.map((m) => m.cost_usd ?? 0))
    return top === 0 ? 0 : ((month.cost_usd ?? 0) / top) * 100
}
