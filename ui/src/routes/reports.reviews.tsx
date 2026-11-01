import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { reviewsReportQuery } from '@/api/queries'
import type {
    ReviewsDay,
    ReviewsEffort,
    ReviewsPullRequest,
    ReviewsReport,
    ReviewsReviewer,
    ReviewsRound,
} from '@/api/types'
import { Age } from '@/components/age'
import { CellBar } from '@/components/cell-bar'
import { ChartTable } from '@/components/chart-table'
import { Cost } from '@/components/cost'
import { DayChart, DayChartLegend } from '@/components/day-chart'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll, PanelSkeleton } from '@/components/panel'
import { PullRequestTable } from '@/components/pull-request-table'
import type { PullRequestColumn } from '@/components/pull-request-table'
import { ReadoutTiles } from '@/components/readout-tiles'
import type { ReadoutTile } from '@/components/readout-tiles'
import { RunLink } from '@/components/run-link'
import { Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Clipped, Hinted } from '@/components/tip'
import { WindowToggle } from '@/components/window-toggle'
import { barPercent } from '@/lib/chart'
import { useClock } from '@/lib/clock'
import { counted } from '@/lib/descriptions'
import { hoursChange, readoutDelta, wholeChange } from '@/lib/readout-delta'
import { windowBefore, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { hoursText } from '@/lib/reports'
import {
    apartText,
    approvedText,
    canopyReviewerFigures,
    DEFAULT_REVIEWS_WINDOW,
    dismissalText,
    draftsHint,
    firstReviewSum,
    LIMITS_TEXT,
    previousReviewsFigures,
    PURPOSE_HINT,
    resumesPerPlan,
    REVIEWS_WINDOWS,
    reviewsBars,
    reviewsFigures,
    reviewsLine,
    reviewsWindow,
    WAIT_SERIES,
} from '@/lib/review-report'
import { dayName } from '@/lib/spend'
import { cn } from '@/lib/utils'

interface ReviewsSearch {
    days?: number | undefined
}

// What the page shows on every visit, on its title's hover: its description is the window's state.
const HELP = [
    "Where review feedback on canopy's PRs came from: how soon each first review came after a PR was ready or asked",
    'for one, who reviews and whether you trust them, the feedback rounds with what each resume cost beside the',
    "planner's estimate, canopy's own reviewer, and each PR.",
    LIMITS_TEXT,
].join(' ')

// What the reviewer table's median wait counts, in its name's tip.
const WAIT_HINT = 'From when each PR began waiting on a review to their first review of it, the median'

// What the reviewer table's columns with a bar count, in their names' tips.
const REVIEWS_HINT = 'The reviews they left, bots and PR authors apart; the bar against the busiest reviewer'
const REVIEWER_WAIT_HINT = `${WAIT_HINT}; the bar against the slowest reviewer`

// What the median first review counts, in its tile's tip, before what it leaves out.
const MEDIAN_HINT = "From when each PR began waiting on a review to its first review, on GitHub's clock, the median"

// What a trusted reviewer's chip means, on its hover.
const TRUSTED_MEANING = 'In trust.trusted_reviewers: a worker addresses their feedback unasked'

// What the estimates' resumes per plan counts, in its name's tip.
const PER_PLAN_HINT = 'The resumes that went ahead on each plan of the estimate; the bar against the most'

// The column names of a table in a padded scrolling region, as the per-PR table's: the head's cells take the padding.
const PADDED_HEAD = 'sticky top-0 bg-surface [&_th]:pt-3'

/**
 * Where the last days' review feedback on canopy's PRs came from: each first review's wait by day, the reviewers,
 * the feedback rounds beside the planner's estimates, canopy's reviewer, and each PR. The window is `?days=`, the
 * week or 30 days; the week, the default, needs no search.
 */
export const Route = createFileRoute('/reports/reviews')({
    // Typed search params: a window the page does not offer is dropped, which reads as the week.
    validateSearch: (search: Record<string, unknown>): ReviewsSearch => ({ days: reviewsWindow(search)?.days }),
    component: ReviewsPage,
})

function ReviewsPage() {
    const search = Route.useSearch()
    const shown: ReportWindow = search.days === undefined ? DEFAULT_REVIEWS_WINDOW : { days: search.days }
    const navigate = Route.useNavigate()
    const query = useQuery(reviewsReportQuery(shown.days ?? 7))
    const span = windowName(shown)
    const { data } = query
    // A read that failed with nothing on screen says so once, in the first panel, with Read again.
    const failed = data === undefined && query.error !== null
    return (
        <>
            <PageHeader
                title="Reviews"
                help={HELP}
                controls={
                    <WindowToggle
                        windows={REVIEWS_WINDOWS}
                        shown={shown}
                        testId="reviews"
                        onPick={(picked) => {
                            void navigate({
                                search: { days: picked === DEFAULT_REVIEWS_WINDOW ? undefined : picked.days },
                            })
                        }}
                    />
                }
                links={
                    !failed && (
                        <ReadoutTiles tiles={reviewsTiles(data)} against={windowBefore(shown)} testId="reviews" />
                    )
                }
            >
                {data === undefined ? (query.isPending ? 'reading the reviews' : null) : reviewsLine(data)}
            </PageHeader>
            <Panel data-testid="reviews-waits">
                <PanelHeader label="First reviews by day" />
                {data === undefined ? (
                    <PanelLoading query={query} className="min-h-72" />
                ) : (
                    <Waits found={data} span={span} />
                )}
            </Panel>
            {!failed && (
                <>
                    <Panel data-testid="reviews-reviewers">
                        <PanelHeader label="Who reviews" />
                        {data === undefined ? (
                            <PanelSkeleton rows={4} className="min-h-32" />
                        ) : (
                            <Reviewers reviewers={data.reviewers} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="reviews-efforts">
                        <PanelHeader label="Estimates" />
                        {data === undefined ? (
                            <PanelSkeleton rows={3} className="min-h-24" />
                        ) : (
                            <Efforts efforts={data.efforts} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="reviews-round-panel">
                        <PanelHeader label="Feedback rounds" />
                        {data === undefined ? (
                            <PanelSkeleton rows={4} className="min-h-32" />
                        ) : (
                            <Rounds rounds={data.rounds} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="reviews-canopy">
                        <PanelHeader label="canopy's reviewer" />
                        {data === undefined ? (
                            <PanelSkeleton rows={3} className="min-h-24" />
                        ) : (
                            <CanopyReviewer found={data} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="reviews-prs">
                        <PanelHeader label="By pull request" />
                        {data === undefined ? (
                            <PanelSkeleton rows={4} className="min-h-32" />
                        ) : data.pull_requests.length === 0 ? (
                            <Empty size="panel">no PR of canopy&apos;s saw anything in these {span}</Empty>
                        ) : (
                            <PullRequestTable
                                rows={data.pull_requests}
                                columns={PR_COLUMNS}
                                label="Reviews by pull request"
                                testId="reviews"
                            />
                        )}
                    </Panel>
                </>
            )}
        </>
    )
}

/**
 * The window's headline figures, each held in its place while the report is read, and each against the window
 * before's: a quicker first review is better.
 */
function reviewsTiles(found: ReviewsReport | undefined): ReadoutTile[] {
    const figures = found === undefined ? undefined : reviewsFigures(found)
    const before = found === undefined ? undefined : previousReviewsFigures(found.previous)
    return [
        {
            key: 'reviews',
            label: 'reviews',
            hint: 'The reviews people left on these PRs, bots and their authors apart',
            value: figures?.reviews,
            delta: readoutDelta(figures?.reviews, before?.reviews, wholeChange),
        },
        {
            key: 'prs',
            label: 'PRs',
            hint: 'The PRs a run named, or that saw feedback, a review asked for, or a merge',
            value: figures?.prs,
            delta: readoutDelta(figures?.prs, before?.prs, wholeChange),
        },
        {
            key: 'first-reviews',
            label: 'first reviews',
            hint: "The first reviews that came, timed on GitHub's clock",
            value: figures?.firstReviews,
            delta: readoutDelta(figures?.firstReviews, before?.firstReviews, wholeChange),
        },
        {
            key: 'median-wait',
            label: 'median first review',
            // What the median leaves out, said here rather than in a sentence over the chart.
            hint: [`${MEDIAN_HINT}.`, found === undefined ? '' : apartText(found)].filter((p) => p !== '').join(' '),
            value: figures === undefined ? undefined : hoursText(figures.medianHours),
            delta: readoutDelta(figures?.medianHours, before?.medianHours, hoursChange, 'down'),
        },
        {
            key: 'rounds',
            label: 'feedback rounds',
            hint: 'The feedback plans written',
            value: figures?.rounds,
            delta: readoutDelta(figures?.rounds, before?.rounds, wholeChange),
        },
    ]
}

/**
 * How soon first reviews came: each day's first reviews stacked by wait, the legend, and a table of the same numbers,
 * since the chart is for the eye. The median is the page's tile, what it leaves out in the tile's tip, and what the
 * page cannot see is in its title's help. A window with no first review timed says so in place of the chart.
 */
function Waits({ found, span }: { found: ReviewsReport; span: string }) {
    const clock = useClock()
    return (
        <div className="flex flex-col gap-4 p-3">
            {found.first_reviews === 0 ? (
                <Empty size="panel">no first review on GitHub&apos;s clock came in these {span}</Empty>
            ) : (
                <>
                    {/* Measured afresh for each window: another count of bars is another pitch. */}
                    <DayChart key={found.per_day.length} bars={reviewsBars(found.per_day, clock)} testId="reviews" />
                    <DayChartLegend series={WAIT_SERIES} testId="reviews" />
                    <ChartTable
                        what={counted(found.per_day.length, 'day')}
                        label="First reviews by day"
                        className="max-h-60 overflow-x-auto"
                    >
                        <table className="w-full border-collapse text-sm" data-testid="reviews-table">
                            <thead className="sticky top-0 bg-surface">
                                <tr className="text-right">
                                    <th className="panel-label pb-1.5 text-left font-normal">day</th>
                                    {WAIT_SERIES.map((s) => (
                                        <th key={s.key} className="panel-label pb-1.5 pl-3 font-normal">
                                            {s.label}
                                        </th>
                                    ))}
                                    <th className="panel-label pb-1.5 pl-3 font-normal">first reviews</th>
                                    <th className="panel-label pb-1.5 pl-3 font-normal">median</th>
                                </tr>
                            </thead>
                            <tbody className="font-mono text-xs">
                                {found.per_day.toReversed().map((day: ReviewsDay) => (
                                    <tr key={day.day} className="text-right" data-testid={`reviews-day-${day.day}`}>
                                        <th scope="row" className="readout py-0.5 text-left font-normal">
                                            {dayName(day, clock)}
                                        </th>
                                        {WAIT_SERIES.map((s, i) => (
                                            <td key={s.key} className="readout pl-3 text-muted-foreground">
                                                {day.first_reviews[i] ?? 0}
                                            </td>
                                        ))}
                                        <td className="readout pl-3">{firstReviewSum(day)}</td>
                                        <td className="readout pl-3 text-muted-foreground">
                                            {hoursText(day.median_wait_hours)}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </ChartTable>
                </>
            )}
        </div>
    )
}

/**
 * Who left feedback, the most reviews first: each login, trusted or not by `trust.trusted_reviewers`, with their
 * reviews, the ones that asked for changes, comments, the PRs they reviewed, and their median wait. Their reviews have
 * a bar against the busiest reviewer's and their wait one against the slowest's, so the busy reviewer and the quick
 * one read without arithmetic. Bots and each PR's own author are left out, as the monthly report leaves them.
 */
function Reviewers({ reviewers, span }: { reviewers: ReviewsReviewer[]; span: string }) {
    if (reviewers.length === 0) {
        return <Empty size="panel">nobody left feedback on canopy&apos;s PRs in these {span}</Empty>
    }
    return (
        <PanelScroll label="Who reviews" className="max-h-96 overflow-x-auto px-3 pb-3">
            <table className="border-collapse text-sm" data-testid="reviews-reviewer-table">
                <thead className={PADDED_HEAD}>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">reviewer</th>
                        <th className="panel-label pb-1.5 pl-3 text-left font-normal">
                            <Hinted hint={REVIEWS_HINT}>reviews</Hinted>
                        </th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">changes</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">comments</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">PRs</th>
                        <th className="panel-label pb-1.5 pl-3 text-left font-normal">
                            <Hinted hint={REVIEWER_WAIT_HINT}>median wait</Hinted>
                        </th>
                    </tr>
                </thead>
                <tbody className="text-xs">
                    {reviewers.map((r) => (
                        <tr key={r.author} className="text-right" data-testid="reviews-reviewer">
                            <th scope="row" className="py-0.5 text-left font-normal">
                                <span className="flex min-w-0 items-center gap-2">
                                    <Clipped text={r.author} mono className="font-mono" />
                                    {r.trusted && (
                                        <Word
                                            word="trusted"
                                            meaning={TRUSTED_MEANING}
                                            className="text-muted-foreground"
                                        />
                                    )}
                                </span>
                            </th>
                            <td className="readout pl-3 text-left">
                                <CellBar
                                    percent={barPercent(
                                        r.reviews,
                                        reviewers.map((x) => x.reviews),
                                    )}
                                    valueClassName="w-6 text-right"
                                >
                                    {r.reviews}
                                </CellBar>
                            </td>
                            <td className={cn('readout pl-3', r.changes_requested > 0 && 'text-status-blocked')}>
                                {r.changes_requested}
                            </td>
                            <td className="readout pl-3 text-muted-foreground">{r.comments}</td>
                            <td className="readout pl-3 text-muted-foreground">{r.pull_requests}</td>
                            <td className="readout pl-3 text-left">
                                <CellBar
                                    percent={barPercent(
                                        r.median_wait_hours,
                                        reviewers.map((x) => x.median_wait_hours),
                                    )}
                                    valueClassName="w-12 text-right"
                                >
                                    {hoursText(r.median_wait_hours)}
                                </CellBar>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}

/** The window's feedback plans, the newest first: each with its ticket, how it was approved, and its run. */
function Rounds({ rounds, span }: { rounds: ReviewsRound[]; span: string }) {
    if (rounds.length === 0) {
        return <Empty size="panel">no feedback plan was written in these {span}</Empty>
    }
    return (
        <PanelScroll label="Feedback plans" className="max-h-96 overflow-x-auto px-3 pb-3">
            <table className="w-full border-collapse text-sm" data-testid="reviews-round-table">
                <thead className={PADDED_HEAD}>
                    <tr className="text-left">
                        <th className="panel-label pb-1.5 font-normal">plan</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">ticket</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">approved by</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">effort</th>
                        <th className="panel-label pb-1.5 pl-3 text-right font-normal">resumes</th>
                        <th className="panel-label pb-1.5 pl-3 text-right font-normal">spent</th>
                        <th className="panel-label pb-1.5 pl-3 text-right font-normal">written</th>
                    </tr>
                </thead>
                <tbody className="text-xs">
                    {rounds.map((r) => (
                        <Round key={r.plan_id} round={r} />
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}

/** A feedback plan's row: its run, its ticket, how it went ahead, its estimate, the resumes after it, what it cost. */
function Round({ round }: { round: ReviewsRound }) {
    const spent = [round.plan_cost_usd, round.resume_cost_usd].filter((c) => c !== null)
    return (
        <tr className="align-top" data-testid={`reviews-round-${round.plan_id}`}>
            <th scope="row" className="py-0.5 text-left font-normal whitespace-nowrap">
                <RunLink id={round.run_id} />
            </th>
            <td className="pl-3 whitespace-nowrap">
                <TicketLink ticketKey={round.ticket_key} />
            </td>
            <td className="w-full pl-3 text-muted-foreground">{approvedText(round)}</td>
            <td className="pl-3 font-mono whitespace-nowrap text-muted-foreground">{round.effort ?? '–'}</td>
            <td className="readout pl-3 text-right">{round.resumes}</td>
            <td className="readout pl-3 text-right text-muted-foreground">
                <Cost usd={spent.length === 0 ? null : spent.reduce((sum, c) => sum + c, 0)} />
            </td>
            <td className="pl-3 text-right whitespace-nowrap">
                <Age at={round.created_at} variant="ago" />
            </td>
        </tr>
    )
}

/**
 * The planner's estimates beside what followed them: per effort, its plans, the resumes that went ahead on them, the
 * resumes per plan with a bar against the most, and what the resumes cost. The receipts for trusting the planner.
 */
function Efforts({ efforts, span }: { efforts: ReviewsEffort[]; span: string }) {
    if (efforts.length === 0) {
        return <Empty size="panel">no feedback plan was written in these {span}</Empty>
    }
    return (
        <div className="px-3 pb-3">
            <table className="border-collapse text-sm" data-testid="reviews-effort-table">
                <thead>
                    <tr className="text-right [&_th]:pt-3">
                        <th className="panel-label pb-1.5 text-left font-normal">planner&apos;s estimate</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">plans</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">resumes</th>
                        <th className="panel-label pb-1.5 pl-3 text-left font-normal">
                            <Hinted hint={PER_PLAN_HINT}>per plan</Hinted>
                        </th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">resumes cost</th>
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {efforts.map((e) => (
                        <tr key={e.effort ?? 'none'} className="text-right" data-testid="reviews-effort">
                            <th scope="row" className="py-0.5 text-left font-normal">
                                {e.effort ?? 'no estimate'}
                            </th>
                            <td className="readout pl-3">{e.plans}</td>
                            <td className="readout pl-3">{e.resumes}</td>
                            <td className="readout pl-3 text-left">
                                <CellBar
                                    percent={barPercent(
                                        resumesPerPlan(e),
                                        efforts.map((x) => resumesPerPlan(x)),
                                    )}
                                    valueClassName="w-8 text-right"
                                >
                                    {resumesPerPlan(e).toFixed(1)}
                                </CellBar>
                            </td>
                            <td className="readout pl-3 text-muted-foreground">
                                <Cost usd={e.resume_cost_usd} />
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

/**
 * canopy's own reviewer: its runs, their cost, the findings you dismissed, and its drafts published, as tiles; under
 * them its runs by purpose and how they ended, and the dismissals by reason, each with a bar against the most. Then
 * whether `trust.trusted_reviewers` lets workers act on it unasked, the setting that changes what the panel means.
 */
function CanopyReviewer({ found, span }: { found: ReviewsReport; span: string }) {
    const figures = canopyReviewerFigures(found)
    const tiles: ReadoutTile[] = [
        { key: 'runs', label: 'runs', hint: 'Its review runs that started in the window', value: figures.runs },
        {
            key: 'cost',
            label: 'cost',
            hint: 'What those runs cost',
            value: <Cost usd={figures.costUsd} />,
        },
        {
            key: 'dismissed',
            label: 'findings dismissed',
            hint: 'The findings of its reviews you dismissed, for a reason below',
            value: figures.dismissed,
        },
        { key: 'published', label: 'drafts published', hint: draftsHint(found), value: figures.published },
    ]
    return (
        <div className="flex flex-col gap-4 p-3">
            <ReadoutTiles tiles={tiles} testId="reviews-canopy" />
            {found.review_runs.length === 0 ? (
                <Empty size="panel">canopy reviewed nothing in these {span}</Empty>
            ) : (
                <table className="self-start border-collapse text-sm" data-testid="reviews-run-table">
                    <thead>
                        <tr className="text-right">
                            <th className="panel-label pb-1.5 text-left font-normal">purpose</th>
                            <th className="panel-label pb-1.5 pl-3 text-left font-normal">ended</th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">runs</th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">spent</th>
                        </tr>
                    </thead>
                    <tbody className="font-mono text-xs">
                        {found.review_runs.map((r) => (
                            <tr key={`${r.purpose}:${r.status}`} className="text-right" data-testid="reviews-run">
                                <th scope="row" className="py-0.5 text-left font-normal">
                                    <Hinted hint={PURPOSE_HINT[r.purpose]}>{r.purpose}</Hinted>
                                </th>
                                <td className="pl-3 text-left text-muted-foreground">
                                    <Word word={r.status} />
                                </td>
                                <td className="readout pl-3">{r.runs}</td>
                                <td className="readout pl-3 text-muted-foreground">
                                    <Cost usd={r.cost_usd} />
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
            {found.dismissals.length > 0 && (
                <table className="self-start border-collapse text-sm" data-testid="reviews-dismissal-table">
                    <thead>
                        <tr>
                            <th className="panel-label pb-1.5 text-left font-normal">dismissed as</th>
                            <th className="panel-label pb-1.5 pl-3 text-left font-normal">findings</th>
                        </tr>
                    </thead>
                    <tbody className="text-xs">
                        {found.dismissals.map((d) => (
                            <tr key={d.reason ?? 'none'} data-testid="reviews-dismissal">
                                <th scope="row" className="py-0.5 text-left font-normal text-muted-foreground">
                                    {dismissalText(d.reason)}
                                </th>
                                <td className="readout w-40 pl-3">
                                    <CellBar
                                        percent={barPercent(
                                            d.findings,
                                            found.dismissals.map((x) => x.findings),
                                        )}
                                        valueClassName="w-6 text-right"
                                    >
                                        {d.findings}
                                    </CellBar>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
            <p className="text-xs text-muted-foreground" data-testid="reviews-canopy-trust">
                {found.canopy_trusted
                    ? 'canopy:review is in trust.trusted_reviewers, so workers address its findings without asking you.'
                    : 'canopy:review is not in trust.trusted_reviewers, so its findings wait for your go-ahead.'}
            </p>
        </div>
    )
}

// What the per-PR table counts of each PR: how soon its first review came, its feedback in the window, its rounds and
// what they cost, and how long it took from ready to merge.
const PR_COLUMNS: readonly PullRequestColumn<ReviewsPullRequest>[] = [
    {
        key: 'first',
        label: 'first review',
        hint: "From when it began waiting on a review to its first review, on GitHub's clock",
        cell: (pr) => hoursText(pr.first_review_hours),
        title: (pr) =>
            pr.waiting_since === null ? 'No ready time from GitHub: read before canopy kept them, or a draft' : '',
    },
    { key: 'reviews', label: 'reviews', cell: (pr) => pr.reviews },
    {
        key: 'changes',
        label: 'changes',
        hint: 'Its reviews that asked for changes',
        cell: (pr) => (
            <span className={cn(pr.changes_requested > 0 && 'text-status-blocked')}>{pr.changes_requested}</span>
        ),
    },
    { key: 'comments', label: 'comments', cell: (pr) => pr.comments, muted: true },
    { key: 'rounds', label: 'rounds', hint: 'Feedback plans that read it', cell: (pr) => pr.rounds },
    {
        key: 'cost',
        label: 'spent',
        hint: 'What its feedback plans and the resumes after them cost',
        cell: (pr) => <Cost usd={pr.cost_usd} />,
        muted: true,
    },
    {
        key: 'merge',
        label: 'ready to merge',
        hint: "From when it last became ready to its merge, on GitHub's clock",
        cell: (pr) => hoursText(pr.hours_to_merge),
        muted: true,
    },
]
