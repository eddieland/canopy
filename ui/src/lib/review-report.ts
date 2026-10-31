// The Reviews page: where review feedback on canopy's PRs came from, how long it took, and what answering it cost.
// The numbers are the server's (`canopy.core.review_report`); this lays them out.

import type { ReviewsDay, ReviewsReport, ReviewsRound } from '@/api/types'
import type { DayBar, DayChartSeries } from '@/lib/chart'
import type { Clock } from '@/lib/clock'
import { counted } from '@/lib/descriptions'
import { pickWindow, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { hoursText } from '@/lib/reports'
import { dayLabel, dayName } from '@/lib/spend'

/** The window the page opens on: the week, as the health and CI pages do. */
export const DEFAULT_REVIEWS_WINDOW: ReportWindow = { days: 7 }

/** The windows the page offers, shortest first, the health page's: whole local days. */
export const REVIEWS_WINDOWS: readonly ReportWindow[] = [DEFAULT_REVIEWS_WINDOW, { days: 30 }]

/** What the page cannot see, as it says under its first reviews. */
export const LIMITS_TEXT =
    "Only the PRs canopy's runs named and a source observed. A PR read before canopy kept GitHub's times has no " +
    "ready time, so its reviews are counted apart. canopy keeps no history of a ticket's phases, so time spent red " +
    'in CI or conflicted is not shown.'

/**
 * The chart's series, one per bucket of a first review's wait, in the server's order, the quickest first: under an
 * hour, one to four hours, four hours to a day, and a day or more. Each in its fill on the wait ramp.
 */
export const WAIT_SERIES: readonly DayChartSeries[] = [
    { key: 'hour', label: 'under 1h', hint: 'First reviews that came within an hour', fill: 'bg-wait-1' },
    { key: 'hours', label: '1–4h', hint: 'First reviews that came in one to four hours', fill: 'bg-wait-2' },
    { key: 'day', label: '4h–1d', hint: 'First reviews that came in four hours to a day', fill: 'bg-wait-3' },
    { key: 'days', label: 'over 1d', hint: 'First reviews that took a day or more', fill: 'bg-wait-4' },
]

// How a feedback plan went ahead, by its approval's channel: the operator through the web or the CLI, or its planner.
const APPROVED_BY: Record<string, string> = {
    web: 'you, on the web',
    cli: 'you, from the CLI',
    planner: 'the planner',
}

/** What a review run's purpose means, on its hover. */
export const PURPOSE_HINT: Record<string, string> = {
    own: "A review of a PR of one of the loop's tickets",
    request: 'A review you asked for',
    query: 'A review of a PR the loop does not own, with no request open',
}

/** What a dismissal's reason means, on its hover; the empty key for a dismissal from before canopy asked why. */
export const DISMISSAL_WORD: Record<string, string> = {
    wrong: 'wrong',
    intentional: 'intentional',
    not_worth_it: 'not worth it',
    out_of_scope: 'out of scope',
    '': 'no reason given',
}

/** The window the search params name, if the page offers it; undefined for the default. */
export function reviewsWindow(search: { days?: unknown }): ReportWindow | undefined {
    return pickWindow(REVIEWS_WINDOWS, search)
}

/**
 * The page's description, the window's state: `38 reviews on 15 PRs · median first review 4.0h over 30 days`, or,
 * with no first review timed, `2 reviews on 1 PR · no first review timed over 7 days`.
 */
export function reviewsLine(
    found: Pick<ReviewsReport, 'days' | 'reviews' | 'pull_requests' | 'median_first_review_hours'>,
): string {
    const median =
        found.median_first_review_hours === null
            ? 'no first review timed'
            : `median first review ${hoursText(found.median_first_review_hours)}`
    const reviews = `${counted(found.reviews, 'review')} on ${counted(found.pull_requests.length, 'PR')}`
    return `${reviews} · ${median} over ${windowName(found)}`
}

/**
 * What the median leaves out, as a sentence beside it: `2 reviewed PRs had no ready time from GitHub and are left
 * out.`, with how many still wait on a first review; empty with neither.
 */
export function apartText(found: Pick<ReviewsReport, 'untimed' | 'waiting'>): string {
    const verb = found.untimed === 1 ? 'is' : 'are'
    const untimed = `${counted(found.untimed, 'reviewed PR')} had no ready time from GitHub and ${verb} left out.`
    const waiting = `${counted(found.waiting, 'open PR')} ${found.waiting === 1 ? 'waits' : 'wait'} on a first review.`
    return [found.untimed === 0 ? '' : untimed, found.waiting === 0 ? '' : waiting].filter((p) => p !== '').join(' ')
}

/** A day's first reviews over every bucket. */
export function firstReviewSum(day: Pick<ReviewsDay, 'first_reviews'>): number {
    return day.first_reviews.reduce((sum, n) => sum + n, 0)
}

/**
 * A day's bar on hover: its date, its first reviews and their median wait, and each bucket that day:
 * `Oct 7: 3 first reviews, median 2.5h; under 1h 1, 1–4h 2`.
 */
export function reviewsDayHint(day: ReviewsDay, clock: Clock): string {
    const total = firstReviewSum(day)
    const head = `${dayName(day, clock)}: ${counted(total, 'first review')}`
    if (total === 0) {
        return head
    }
    const named = WAIT_SERIES.flatMap((s, i) => {
        const n = day.first_reviews[i] ?? 0
        return n > 0 ? [`${s.label} ${n}`] : []
    })
    return `${head}, median ${hoursText(day.median_wait_hours)}; ${named.join(', ')}`
}

/** Each day as the waits chart draws it: its first reviews, by wait bottom up, the quickest first. */
export function reviewsBars(days: readonly ReviewsDay[], clock: Clock): DayBar[] {
    return days.map((day) => {
        const total = firstReviewSum(day)
        return {
            key: day.day,
            label: dayLabel(day, clock),
            hint: reviewsDayHint(day, clock),
            total,
            totalText: String(total),
            segments: WAIT_SERIES.map((s, i) => ({ key: s.key, fill: s.fill, value: day.first_reviews[i] ?? 0 })),
        }
    })
}

/** How a feedback plan went ahead, `the planner` or `you, on the web`; `not approved` for one waiting or replaced. */
export function approvedText(round: Pick<ReviewsRound, 'approved_channel'>): string {
    const channel = round.approved_channel
    return channel === null ? 'not approved' : (APPROVED_BY[channel] ?? channel)
}

/** A dismissal's reason in words; `no reason given` for one from before canopy asked. */
export function dismissalText(reason: string | null): string {
    return DISMISSAL_WORD[reason ?? ''] ?? reason ?? ''
}
