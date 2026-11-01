// The CI page: which checks fail, what fixing them cost, and whether flaky kicks worked, on the PRs canopy observed.
// The numbers are the server's; this lays them out.

import type { CiCheck, CiDay, CiFix, CiKick, CiPrevious, CiPullRequest, CiReport, CiVerdict } from '@/api/types'
import type { DayBar, DayChartSeries } from '@/lib/chart'
import type { Clock } from '@/lib/clock'
import { counted } from '@/lib/descriptions'
import { pickWindow, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { hoursText } from '@/lib/reports'
import { dayLabel, dayName, shareText } from '@/lib/spend'

/** The window the page opens on: the week, as the health page does. */
export const DEFAULT_CI_WINDOW: ReportWindow = { days: 7 }

/** The windows the page offers, shortest first, the health page's: whole local days. */
export const CI_WINDOWS: readonly ReportWindow[] = [DEFAULT_CI_WINDOW, { days: 30 }]

/** What the page says counts as red, green, and neither, as the server counts a check run. */
export const VERDICTS_TEXT =
    'Red is failure, error, timed_out, or startup_failure, and green is success; cancelled, skipped, neutral, stale, ' +
    'and action_required count as neither.'

/** What the page cannot see, as it says under its checks. */
export const LIMITS_TEXT =
    'Only the PRs canopy observed, and only their check runs from M36 on. A commit status has no check run, so it ' +
    'has no history and is not counted.'

// The checks' fills by rank, the most often red first, written out so Tailwind finds them; the rest is a neutral.
const CHECK_FILLS = ['bg-check-1', 'bg-check-2', 'bg-check-3', 'bg-check-4'] as const
const OTHER_FILL = 'bg-check-other'
/** The key of the series that sums every check the chart does not name apart. */
export const OTHER = 'other'

/** The window the search params name, if the page offers it; undefined for the default. */
export function ciWindow(search: { days?: unknown }): ReportWindow | undefined {
    return pickWindow(CI_WINDOWS, search)
}

/**
 * The page's description, the window's state: `40% of PR heads green first time · 4 flaky kicks over 7 days`, or,
 * with no head checked, `no PR head checked · no flaky kicks over 7 days`.
 */
export function ciLine(found: Pick<CiReport, 'days' | 'heads' | 'green_first' | 'kicks'>): string {
    const heads =
        found.heads === 0
            ? 'no PR head checked'
            : `${shareText(found.green_first / found.heads)} of PR heads green first time`
    return `${heads} · ${counted(found.kicks.length, 'flaky kick')} over ${windowName(found)}`
}

/** The window's headline figures, as the page's tiles show them. */
export interface CiFigures {
    /** The PR heads first checked in the window. */
    heads: number
    /** Their share whose first run of every check was not red; null with none checked. */
    greenFirst: number | null
    /** The red check runs, over every day. */
    red: number
    /** The resumes for CI that started in the window. */
    fixes: number
    /** Of those, the ones whose every check red when they started was green on the head after them. */
    fixesGreen: number
}

/** The window's heads, their share green first time, its red runs, and its fix-CI resumes and how many went green. */
export function ciFigures(found: Pick<CiReport, 'heads' | 'green_first' | 'per_day' | 'fixes'>): CiFigures {
    return {
        heads: found.heads,
        greenFirst: found.heads === 0 ? null : found.green_first / found.heads,
        red: found.per_day.reduce((sum, day) => sum + redSum(day), 0),
        fixes: found.fixes.length,
        fixesGreen: found.fixes.filter((f) => wentGreen(f)).length,
    }
}

/** The window before's headline figures, as `ciFigures` reads the window's. */
export function previousCiFigures(previous: CiPrevious): CiFigures {
    return {
        heads: previous.heads,
        greenFirst: previous.heads === 0 ? null : previous.green_first / previous.heads,
        red: previous.red,
        fixes: previous.fixes,
        fixesGreen: previous.fixes_green,
    }
}

/**
 * Whether a fix went green: it found a check red when it started, and every one it found was green on the head after
 * it, as the server counts the window before's.
 */
export function wentGreen(fix: Pick<CiFix, 'checks'>): boolean {
    return fix.checks.length > 0 && fix.checks.every((c) => c.next === 'green')
}

/**
 * The chart's series, from the server's names: each check it names apart, by rank, in its fill, then the rest as
 * `other` in the neutral. A series' key is its place, `check-0`, since a check's name may hold any character.
 */
export function ciSeries(series: readonly (string | null)[]): DayChartSeries[] {
    let named = 0
    return series.map((name) => {
        if (name === null) {
            return { key: OTHER, label: OTHER, hint: 'Every other check, summed', fill: OTHER_FILL }
        }
        const fill = CHECK_FILLS[named] ?? OTHER_FILL
        named += 1
        return { key: `check-${named - 1}`, label: name, hint: `The ${name} check's red runs`, fill }
    })
}

/** A day's red runs over every series. */
export function redSum(day: Pick<CiDay, 'red'>): number {
    return day.red.reduce((sum, n) => sum + n, 0)
}

/**
 * A day's bar on hover: its date, its red runs, and each series red that day, by the legend's names:
 * `Oct 7: 3 red, e2e 2, unit 1`.
 */
export function ciDayHint(day: CiDay, series: readonly DayChartSeries[], clock: Clock): string {
    const head = `${dayName(day, clock)}: ${redSum(day)} red`
    const named = series.flatMap((s, i) => {
        const n = day.red[i] ?? 0
        return n > 0 ? [`${s.label} ${n}`] : []
    })
    return named.length === 0 ? head : `${head}, ${named.join(', ')}`
}

/** Each day as the red checks chart draws it: its red runs, by series bottom up. */
export function ciBars(days: readonly CiDay[], series: readonly DayChartSeries[], clock: Clock): DayBar[] {
    return days.map((day) => {
        const total = redSum(day)
        return {
            key: day.day,
            label: dayLabel(day, clock),
            hint: ciDayHint(day, series, clock),
            total,
            totalText: String(total),
            segments: series.map((s, i) => ({ key: s.key, fill: s.fill, value: day.red[i] ?? 0 })),
        }
    })
}

/** A check's share of red among its red and green runs, `60%`, or `–` with neither. */
export function failureRate(check: Pick<CiCheck, 'red' | 'green'>): string {
    return shareText(failureShare(check))
}

/** A check's red runs' share of its red and green ones, 0 to 1; null when it had neither. */
export function failureShare(check: Pick<CiCheck, 'red' | 'green'>): number | null {
    const judged = check.red + check.green
    return judged === 0 ? null : check.red / judged
}

/** How often a check's next run on a new head passed after a red one: `2 of 3`, or `–` when none followed. */
export function nextHeadText(check: Pick<CiCheck, 'followed' | 'passed'>): string {
    return check.followed === 0 ? '–' : `${check.passed} of ${check.followed}`
}

/** A fixed check's next run in words: how it counted, or `not yet` while no source has observed one. */
export function nextText(next: CiVerdict | null): string {
    return next ?? 'not yet'
}

/**
 * The fixes' red-to-green rate, the only one the journal can give: `2 of 3 checks green on the next head`; empty with
 * no check judged yet.
 */
export function fixRateText(fixes: readonly Pick<CiFix, 'checks'>[]): string {
    const judged = fixes.flatMap((f) => f.checks).filter((c) => c.next === 'green' || c.next === 'red')
    if (judged.length === 0) {
        return ''
    }
    const green = judged.filter((c) => c.next === 'green').length
    return `${green} of ${counted(judged.length, 'check')} green on the next head`
}

/** A kick against the limit: `kick 2 of 3`, or `kick 2` with kicks now off. */
export function kickText(kick: Pick<CiKick, 'kick'>, limit: number): string {
    return limit === 0 ? `kick ${kick.kick}` : `kick ${kick.kick} of ${limit}`
}

/** How many green reruns on an unchanged head make a check flaky, as its chip says: one could be the fix landing. */
export const FLAKY_RERUNS = 2

/** A check's reruns on a head it was red on that went green: `1 of 2`, or `–` with no rerun. */
export function rerunsText(check: Pick<CiCheck, 'reruns' | 'reruns_green'>): string {
    return check.reruns === 0 ? '–' : `${check.reruns_green} of ${check.reruns}`
}

/** Whether a check passed on a head it had failed on often enough to call flaky, without anyone's say-so. */
export function isFlaky(check: Pick<CiCheck, 'reruns_green'>): boolean {
    return check.reruns_green >= FLAKY_RERUNS
}

/** Of a check's red runs a new head followed, the share whose next run passed, 0 to 1; null when none followed. */
export function nextHeadShare(check: Pick<CiCheck, 'followed' | 'passed'>): number | null {
    return check.followed === 0 ? null : check.passed / check.followed
}

/** The green-first chart's series, bottom up: the heads green first time, then the rest. */
export const GREEN_FIRST_SERIES: readonly DayChartSeries[] = [
    {
        key: 'green-first',
        label: 'green first time',
        hint: 'PR heads whose first run of every check was not red',
        fill: 'bg-accent',
    },
    {
        key: 'red-first',
        label: 'red first',
        hint: 'PR heads with a check whose first run was red',
        fill: 'bg-check-other',
    },
]

/** A day's heads' share green first time as a readout: `50%`, or a dash with no head first checked. */
export function greenFirstRateText(day: Pick<CiDay, 'heads' | 'green_first'>): string {
    return shareText(day.heads === 0 ? null : day.green_first / day.heads)
}

/** A day's bar on hover: `Oct 8: 3 of 6 heads green first time, 50%`, or `Oct 5: no head checked`. */
export function greenFirstHint(day: CiDay, clock: Clock): string {
    const name = dayName(day, clock)
    return day.heads === 0
        ? `${name}: no head checked`
        : `${name}: ${day.green_first} of ${counted(day.heads, 'head')} green first time, ${greenFirstRateText(day)}`
}

/** Each day as the green-first chart draws it: its heads first checked, the green-first ones at the bottom. */
export function greenFirstBars(days: readonly CiDay[], clock: Clock): DayBar[] {
    return days.map((day) => ({
        key: day.day,
        label: dayLabel(day, clock),
        hint: greenFirstHint(day, clock),
        total: day.heads,
        totalText: String(day.heads),
        segments: [
            { key: 'green-first', fill: 'bg-accent', value: day.green_first },
            { key: 'red-first', fill: 'bg-check-other', value: day.heads - day.green_first },
        ],
    }))
}

/** What the time to green says of a PR: its hours, `still red` while its spell lasts, or a dash when it never was. */
export function toGreenText(pr: Pick<CiPullRequest, 'red_at' | 'hours_to_green'>): string {
    if (pr.red_at === null) {
        return '–'
    }
    return pr.hours_to_green === null ? 'still red' : hoursText(pr.hours_to_green)
}

/**
 * How long a fix's PRs took to go green from the red they were in when it started: its hours, `still red` while one
 * is, or a dash when no check was red.
 */
export function fixToGreenText(fix: Pick<CiFix, 'checks' | 'hours_to_green'>): string {
    if (fix.checks.length === 0) {
        return '–'
    }
    return fix.hours_to_green === null ? 'still red' : hoursText(fix.hours_to_green)
}

/** What the page says of its time to green, under the per-PR table: when it measures, and how roughly. */
export const TO_GREEN_TEXT =
    "From a PR's first red check run to its first head with every check green, on when canopy saw each run finish, " +
    'not when it did: a head whose other checks are still running reads green until one is seen red.'
