// The window a report page reads over (ui/DESIGN.md, "The spend chart"): a number of local days, today's so far
// included, or of clock hours. Each page offers a few, and keeps the one shown in its search params.

import type { SpendBreakdownRange } from '@/api/queries'

/** A window a report reads over: whole local days, or clock hours. */
export type ReportWindow = SpendBreakdownRange

/** A window's length in words, from its search params or the report read over it: `24 hours`, `7 days`. */
export function windowName(range: { days?: number | null; hours?: number | null }): string {
    const [n, unit] =
        range.hours === undefined || range.hours === null ? [range.days ?? 0, 'day'] : [range.hours, 'hour']
    return n === 1 ? `1 ${unit}` : `${n} ${unit}s`
}

/** A window's id, its toggle's value and test id: the hours with an `h`, `24h`, or the days, `7`. */
export function windowId(range: ReportWindow): string {
    return range.hours === undefined ? String(range.days) : `${range.hours}h`
}

/** The window of `offered` the search params name, hours before days; undefined for one not offered. */
export function pickWindow(
    offered: readonly ReportWindow[],
    search: { days?: unknown; hours?: unknown },
): ReportWindow | undefined {
    return (
        offered.find((w) => w.hours !== undefined && names(search.hours, w.hours)) ??
        offered.find((w) => w.days !== undefined && names(search.days, w.days))
    )
}

// Whether a search param names `n`, as a number or as its digits.
function names(value: unknown, n: number): boolean {
    return n === value || String(n) === value
}

/** The window before a window, as a tile's delta says it: `the 7 days before`, `the 24 hours before`. */
export function windowBefore(range: { days?: number | null; hours?: number | null }): string {
    return `the ${windowName(range)} before`
}
