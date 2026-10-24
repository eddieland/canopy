// The reports page: what each local calendar month cost, in dollars and tokens, and what it got done. The numbers are
// the server's (`canopy.core.monthly`); this lays them out.

import type { ReportMonth, ReportTokens } from '@/api/types'
import { costText } from '@/lib/cost-total'
import { counted } from '@/lib/descriptions'

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

/** A month's cost as a share of the dearest month's, 0 to 100, for its bar; 0 when nothing cost anything. */
export function costPercent(month: ReportMonth, months: readonly ReportMonth[]): number {
    const top = Math.max(0, ...months.map((m) => m.cost_usd ?? 0))
    return top === 0 ? 0 : ((month.cost_usd ?? 0) / top) * 100
}
