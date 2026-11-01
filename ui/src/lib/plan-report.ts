// The Plans page: how plans were approved, by the level of `policy.planner_may_approve` their planners were offered,
// and what their PRs needed after. The numbers are the server's (`canopy.core.plan_report`); this lays them out.

import type { PlanLevel, PlanOutcome, PlansGroup, PlansLength, PlansReport, PlansRow } from '@/api/types'
import { sizeText } from '@/lib/attachments'
import { counted } from '@/lib/descriptions'
import { pickWindow, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'

/** The window the page opens on: 30 days, since a week rarely holds enough plans to judge a level by. */
export const DEFAULT_PLANS_WINDOW: ReportWindow = { days: 30 }

/** The windows the page offers, shortest first: whole local days. */
export const PLANS_WINDOWS: readonly ReportWindow[] = [DEFAULT_PLANS_WINDOW, { days: 90 }]

/** What the page cannot see, as it says under its levels. */
export const LIMITS_TEXT =
    'A plan run from before canopy kept the level it was offered shows as not recorded. A ticket keeps adding ' +
    "resumes until it is done, so an open one's count may grow. Feedback plans are on the Reviews page."

/** Each outcome in words, as the tables name it. */
export const OUTCOME_WORD: Record<PlanOutcome, string> = {
    planner: 'by the planner',
    as_written: 'as written',
    revised: 'revised',
    replaced: 'sent back',
    dropped: 'dropped',
    waiting: 'waiting on you',
}

/** What each outcome means, on its hover. */
export const OUTCOME_HINT: Record<PlanOutcome, string> = {
    planner: 'Approved on its planner’s word that it needs no review',
    as_written: 'You approved the ticket’s first plan as its planner wrote it, with no comment on it',
    revised: 'You approved it after editing it or commenting on it, or after sending an earlier plan back',
    replaced: 'A newer plan replaced it before it was approved: you asked for changes, or for a new plan',
    dropped: 'Superseded with no plan after it: skipped, or forgotten',
    waiting: 'Proposed, waiting on you',
}

/** What each level lets the planner waive, on its hover; the empty key for a run that kept none. */
export const LEVEL_HINT: Record<PlanLevel | '', string> = {
    off: 'The planner was not asked: every plan waits on you',
    strict: 'The planner may waive your review of a plan that leaves you nothing to judge',
    normal: 'The planner may waive your review of a plan that follows the code’s patterns within the ticket’s scope',
    lenient: 'The planner may waive your review of its confident best reading of the ticket',
    '': 'Written before canopy kept the level a plan run was offered',
}

/** The window the search params name, if the page offers it; undefined for one it does not. */
export function plansWindow(search: { days?: unknown }): ReportWindow | undefined {
    return pickWindow(PLANS_WINDOWS, search)
}

/** A level as the tables name it: its own word, or `not recorded` for a run that kept none. */
export function levelText(level: PlanLevel | null): string {
    return level ?? 'not recorded'
}

/**
 * The page's description, the window's state: `9 plans · 5 approved, 2 by the planner · 2 of 5 PRs needed a resume
 * over 30 days`, or `no plans over 7 days`.
 */
export function plansLine(found: Pick<PlansReport, 'days' | 'plans' | 'outcomes' | 'groups'>): string {
    const over = `over ${windowName(found)}`
    if (found.plans.length === 0) {
        return `no plans ${over}`
    }
    const approved = approvedCount(found.outcomes)
    const parts = [
        counted(found.plans.length, 'plan'),
        `${approved} approved, ${found.outcomes.planner ?? 0} by the planner`,
    ]
    const implemented = found.groups.reduce((sum, g) => sum + g.implemented, 0)
    if (implemented > 0) {
        const resumed = found.groups.reduce((sum, g) => sum + g.with_resume, 0)
        parts.push(`${resumed} of ${counted(implemented, 'PR')} needed a resume`)
    }
    return `${parts.join(' · ')} ${over}`
}

/** How many of a window's plans were approved, the planner's and yours. */
export function approvedCount(outcomes: Record<string, number>): number {
    return (outcomes.planner ?? 0) + (outcomes.as_written ?? 0) + (outcomes.revised ?? 0)
}

/** A group's PRs that needed a resume, of those an `implement` followed: `1 of 2`; a dash with none implemented. */
export function resumedText(group: Pick<PlansGroup, 'implemented' | 'with_resume'>): string {
    return group.implemented === 0 ? '–' : `${group.with_resume} of ${group.implemented}`
}

/**
 * A plan's size in pages, to the nearest half and never under one: `≈ ½ page`, `≈ 1 page`, `≈ 2½ pages`. A page is
 * the server's `page_bytes`, about 500 words, so it is a reading of how long the plan looks, not a count.
 */
export function pagesText(size: number, pageBytes: number): string {
    const halves = Math.max(1, Math.round((2 * size) / pageBytes))
    const whole = Math.floor(halves / 2)
    const pages = `${whole === 0 ? '' : String(whole)}${halves % 2 === 1 ? '½' : ''}`
    return `≈ ${pages} ${halves <= 2 ? 'page' : 'pages'}`
}

/** A size bucket in pages: `under 1 page`, `2–4 pages`, `4 pages and up`. The server cuts them at whole pages. */
export function lengthText(length: Pick<PlansLength, 'low' | 'high'>, pageBytes: number): string {
    const low = length.low / pageBytes
    if (length.high === null) {
        return `${String(low)} ${low === 1 ? 'page' : 'pages'} and up`
    }
    const high = length.high / pageBytes
    if (length.low === 0) {
        return `under ${String(high)} ${high === 1 ? 'page' : 'pages'}`
    }
    return `${String(low)}–${String(high)} pages`
}

/** A size bucket in bytes, on its hover: `under 2.9 KiB`, `5.9–11.7 KiB`, `11.7 KiB and up`. */
export function lengthBytesText(length: Pick<PlansLength, 'low' | 'high'>): string {
    if (length.high === null) {
        return `${sizeText(length.low)} and up`
    }
    if (length.low === 0) {
        return `under ${sizeText(length.high)}`
    }
    return `${sizeText(length.low).replace(' KiB', '')}–${sizeText(length.high)}`
}

/**
 * What changed before a plan's approval, in words: `edited`, `2 comments`, `after 1 sent back`, joined; empty for
 * none.
 */
export function changesText(row: Pick<PlansRow, 'edited' | 'comments' | 'earlier'>): string {
    const parts = [
        row.edited ? 'edited' : '',
        row.comments === 0 ? '' : counted(row.comments, 'comment'),
        row.earlier === 0 ? '' : `after ${row.earlier} sent back`,
    ]
    return parts.filter((p) => p !== '').join(', ')
}

/** Why a plan's ticket's resumes ran, on the count's hover: `ci 1, review 2`; empty for none. */
export function reasonsText(reasons: Record<string, number>): string {
    return Object.entries(reasons)
        .map(([reason, n]) => `${reason} ${n}`)
        .join(', ')
}
