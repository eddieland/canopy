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
    ReviewsRunCount,
} from '@/api/types'
import { Age } from '@/components/age'
import { ChartTable } from '@/components/chart-table'
import { Cost } from '@/components/cost'
import { DayChart, DayChartLegend } from '@/components/day-chart'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelSkeleton } from '@/components/panel'
import { PullRequestTable } from '@/components/pull-request-table'
import type { PullRequestColumn } from '@/components/pull-request-table'
import { ReadoutTiles } from '@/components/readout-tiles'
import type { ReadoutTile } from '@/components/readout-tiles'
import { ReportTable } from '@/components/report-table'
import type { ReportColumn } from '@/components/report-table'
import { RunLink } from '@/components/run-link'
import { Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Clipped, Hinted, Tipped } from '@/components/tip'
import { WindowToggle } from '@/components/window-toggle'
import { barPercent } from '@/lib/chart'
import { useClock } from '@/lib/clock'
import type { Clock } from '@/lib/clock'
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
    ROUND_TURNAROUND_HINT,
    roundsToApprovalTitle,
    roundTurnaroundTitle,
    reviewsBars,
    reviewsFigures,
    reviewsLine,
    reviewsWindow,
    turnaroundHint,
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
    'for one, who reviews and whether you trust them, the feedback rounds with how long canopy took to answer each and',
    "what its resumes cost beside the planner's estimate, canopy's own reviewer, and each PR to its approval.",
    LIMITS_TEXT,
].join(' ')

// What the reviewer table's median wait counts, in its name's tip.
const WAIT_HINT = 'From when each PR began waiting on a review to their first review of it, the median'

// What the reviewer table's columns with a bar count, in their names' tips.
const REVIEWS_HINT = 'The reviews they left, bots and PR authors apart; the bar against the busiest reviewer'
const REVIEWER_WAIT_HINT = `${WAIT_HINT}; the bar against the slowest reviewer`

// What the median first review counts, in its tile's tip, before what it leaves out.
const MEDIAN_HINT = "From when each PR began waiting on a review to its first review, on GitHub's clock, the median"

// What a PR's first review counts, in its column's tip, before its bar.
const PR_FIRST_HINT = "From when it began waiting on a review to its first review, on GitHub's clock"

// What the median turnaround counts, in its tile's tip while the report is read.
const TURNAROUND_HINT = 'From the review that started a feedback round to the push that answered it, the median'

// What a trusted reviewer's chip means, on its hover.
const TRUSTED_MEANING = 'In trust.trusted_reviewers: a worker addresses their feedback unasked'

// What the estimates' resumes per plan counts, in its name's tip.
const PER_PLAN_HINT = 'The resumes that went ahead on each plan of the estimate; the bar against the most'

// A reason canopy's review findings were dismissed for, and how many were.
type Dismissal = ReviewsReport['dismissals'][number]

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
                                columns={prColumns(data.pull_requests)}
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
 * before's where the page has it: a quicker first review is better. canopy's median turnaround has its parts in its
 * tip.
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
        {
            // canopy's side of the clock; the window before has no figure of it, so it has no delta.
            key: 'turnaround',
            label: 'median turnaround',
            hint: found === undefined ? TURNAROUND_HINT : turnaroundHint(found),
            value: found === undefined ? undefined : hoursText(found.median_turnaround_hours),
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
                        <ReportTable
                            rows={found.per_day.toReversed()}
                            columns={dayColumns(clock)}
                            rowKey={(day) => day.day}
                            label="First reviews by day"
                            scroll={false}
                            testId="reviews-table"
                            rowTestId={(day) => `reviews-day-${day.day}`}
                        />
                    </ChartTable>
                </>
            )}
        </div>
    )
}

/** The first-reviews-by-day table's columns: the day, its first reviews by wait, their sum, and its median wait. */
function dayColumns(clock: Clock): ReportColumn<ReviewsDay>[] {
    return [
        {
            key: 'day',
            kind: 'name',
            label: 'day',
            cell: (day) => <span className="readout">{dayName(day, clock)}</span>,
        },
        ...WAIT_SERIES.map((series, i): ReportColumn<ReviewsDay> => ({
            key: series.key,
            kind: 'figure',
            label: series.label,
            cell: (day) => day.first_reviews[i] ?? 0,
            muted: true,
        })),
        { key: 'first', kind: 'figure', label: 'first reviews', cell: firstReviewSum },
        {
            key: 'median',
            kind: 'figure',
            label: 'median',
            cell: (day) => hoursText(day.median_wait_hours),
            muted: true,
        },
    ]
}

/**
 * Who left feedback, the most reviews first: each login, trusted or not by `trust.trusted_reviewers`, with their
 * reviews, the ones that asked for changes and that approved, comments, the PRs they reviewed, and their median wait.
 * Their reviews have a bar against the busiest reviewer's and their wait one against the slowest's, so the busy
 * reviewer and the quick one read without arithmetic. Bots and each PR's own author are left out, as the monthly
 * report leaves them.
 */
function Reviewers({ reviewers, span }: { reviewers: ReviewsReviewer[]; span: string }) {
    if (reviewers.length === 0) {
        return <Empty size="panel">nobody left feedback on canopy&apos;s PRs in these {span}</Empty>
    }
    return (
        <ReportTable
            rows={reviewers}
            columns={reviewerColumns(reviewers)}
            rowKey={(r) => r.author}
            label="Who reviews"
            testId="reviews-reviewer-table"
            rowTestId="reviews-reviewer"
        />
    )
}

/**
 * The reviewer table's columns: the login, marked when trusted; their reviews, with a bar against the busiest; the
 * reviews that asked for changes and that approved; comments; PRs; and their median wait, with a bar against the
 * slowest.
 */
function reviewerColumns(reviewers: readonly ReviewsReviewer[]): ReportColumn<ReviewsReviewer>[] {
    const reviews = reviewers.map((r) => r.reviews)
    const waits = reviewers.map((r) => r.median_wait_hours)
    return [
        {
            key: 'reviewer',
            kind: 'name',
            label: 'reviewer',
            cell: (r) => (
                <span className="flex min-w-0 items-center gap-2">
                    <Clipped text={r.author} mono className="font-mono" />
                    {r.trusted && <Word word="trusted" meaning={TRUSTED_MEANING} className="text-muted-foreground" />}
                </span>
            ),
        },
        {
            key: 'reviews',
            kind: 'bar',
            label: 'reviews',
            hint: REVIEWS_HINT,
            cell: (r) => r.reviews,
            bar: (r) => barPercent(r.reviews, reviews),
        },
        {
            key: 'changes',
            kind: 'figure',
            label: 'changes',
            cell: (r) => r.changes_requested,
            tone: (r) => r.changes_requested > 0 && 'text-status-blocked',
        },
        {
            key: 'approved',
            kind: 'figure',
            label: 'approved',
            cell: (r) => r.approved,
            tone: (r) => r.approved > 0 && 'text-status-done',
        },
        { key: 'comments', kind: 'figure', label: 'comments', cell: (r) => r.comments, muted: true },
        { key: 'prs', kind: 'figure', label: 'PRs', cell: (r) => r.pull_requests, muted: true },
        {
            key: 'wait',
            kind: 'bar',
            label: 'median wait',
            hint: REVIEWER_WAIT_HINT,
            cell: (r) => hoursText(r.median_wait_hours),
            bar: (r) => barPercent(r.median_wait_hours, waits),
        },
    ]
}

/**
 * The window's feedback plans, the newest first: each with its ticket, how it was approved, and its run, and canopy's
 * turnaround on it, from the review that started it to the push that answered it.
 */
function Rounds({ rounds, span }: { rounds: ReviewsRound[]; span: string }) {
    if (rounds.length === 0) {
        return <Empty size="panel">no feedback plan was written in these {span}</Empty>
    }
    return (
        <ReportTable
            rows={rounds}
            columns={ROUND_COLUMNS}
            rowKey={(r) => String(r.plan_id)}
            label="Feedback plans"
            testId="reviews-round-table"
            rowTestId={(r) => `reviews-round-${r.plan_id}`}
        />
    )
}

/**
 * A feedback plan's columns: its run, its ticket, how it went ahead, its estimate, the resumes after it, what it cost,
 * and its turnaround, with its parts or why it has none in the time's tip, and when it was written.
 */
const ROUND_COLUMNS: ReportColumn<ReviewsRound>[] = [
    { key: 'plan', kind: 'name', label: 'plan', cell: (r) => <RunLink id={r.run_id} /> },
    { key: 'ticket', kind: 'word', label: 'ticket', cell: (r) => <TicketLink ticketKey={r.ticket_key} /> },
    {
        key: 'approved',
        kind: 'free',
        label: 'approved by',
        cell: (r) => <Clipped text={approvedText(r)} className="block" />,
        muted: true,
    },
    {
        key: 'effort',
        kind: 'word',
        label: 'effort',
        cell: (r) => <span className="font-mono">{r.effort ?? '–'}</span>,
        muted: true,
    },
    { key: 'resumes', kind: 'figure', label: 'resumes', cell: (r) => r.resumes },
    { key: 'spent', kind: 'figure', label: 'spent', cell: roundCost, muted: true },
    {
        key: 'turnaround',
        kind: 'figure',
        label: 'turnaround',
        hint: ROUND_TURNAROUND_HINT,
        // The cell's own test id, so a test finds the time a round took.
        cell: (r) => (
            <span data-testid="reviews-round-turnaround">
                <Tipped fact={roundTurnaroundTitle(r)}>{hoursText(r.turnaround_hours)}</Tipped>
            </span>
        ),
    },
    { key: 'written', kind: 'age', label: 'written', cell: (r) => <Age at={r.created_at} variant="ago" /> },
]

/** What a feedback plan and the resumes after it cost; null when neither reported a cost. */
function roundCost(round: ReviewsRound) {
    const spent = [round.plan_cost_usd, round.resume_cost_usd].filter((c) => c !== null)
    return <Cost usd={spent.length === 0 ? null : spent.reduce((sum, c) => sum + c, 0)} />
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
        <ReportTable
            rows={efforts}
            columns={effortColumns(efforts)}
            rowKey={(e) => e.effort ?? 'none'}
            label="Estimates"
            testId="reviews-effort-table"
            rowTestId="reviews-effort"
        />
    )
}

/** The estimates table's columns: the effort, its plans, their resumes, the resumes per plan, and what they cost. */
function effortColumns(efforts: readonly ReviewsEffort[]): ReportColumn<ReviewsEffort>[] {
    const perPlan = efforts.map((e) => resumesPerPlan(e))
    return [
        {
            key: 'effort',
            kind: 'name',
            label: "planner's estimate",
            cell: (e) => <span className="font-mono">{e.effort ?? 'no estimate'}</span>,
        },
        { key: 'plans', kind: 'figure', label: 'plans', cell: (e) => e.plans },
        { key: 'resumes', kind: 'figure', label: 'resumes', cell: (e) => e.resumes },
        {
            key: 'per-plan',
            kind: 'bar',
            label: 'per plan',
            hint: PER_PLAN_HINT,
            cell: (e) => resumesPerPlan(e).toFixed(1),
            bar: (e) => barPercent(resumesPerPlan(e), perPlan),
        },
        {
            key: 'cost',
            kind: 'figure',
            label: 'resumes cost',
            cell: (e) => <Cost usd={e.resume_cost_usd} />,
            muted: true,
        },
    ]
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
                <ReportTable
                    rows={found.review_runs}
                    columns={RUN_COLUMNS}
                    rowKey={(r) => `${r.purpose}:${r.status}`}
                    label="canopy's review runs"
                    className="self-start"
                    testId="reviews-run-table"
                    rowTestId="reviews-run"
                />
            )}
            {found.dismissals.length > 0 && (
                <ReportTable
                    rows={found.dismissals}
                    columns={dismissalColumns(found.dismissals)}
                    rowKey={(d) => d.reason ?? 'none'}
                    label="Findings dismissed"
                    className="self-start"
                    testId="reviews-dismissal-table"
                    rowTestId="reviews-dismissal"
                />
            )}
            <p className="text-xs text-muted-foreground" data-testid="reviews-canopy-trust">
                {found.canopy_trusted
                    ? 'canopy:review is in trust.trusted_reviewers, so workers address its findings without asking you.'
                    : 'canopy:review is not in trust.trusted_reviewers, so its findings wait for your go-ahead.'}
            </p>
        </div>
    )
}

/** canopy's review runs' columns: their purpose, how they ended, how many, and what they cost. */
const RUN_COLUMNS: ReportColumn<ReviewsRunCount>[] = [
    {
        key: 'purpose',
        kind: 'name',
        label: 'purpose',
        cell: (r) => (
            <span className="font-mono">
                <Hinted hint={PURPOSE_HINT[r.purpose]}>{r.purpose}</Hinted>
            </span>
        ),
    },
    {
        key: 'ended',
        kind: 'word',
        label: 'ended',
        cell: (r) => (
            <span className="font-mono">
                <Word word={r.status} />
            </span>
        ),
        muted: true,
    },
    { key: 'runs', kind: 'figure', label: 'runs', cell: (r) => r.runs },
    { key: 'spent', kind: 'figure', label: 'spent', cell: (r) => <Cost usd={r.cost_usd} />, muted: true },
]

/** The dismissals' columns: the reason, and its findings with a bar against the most. */
function dismissalColumns(dismissals: readonly Dismissal[]): ReportColumn<Dismissal>[] {
    const findings = dismissals.map((d) => d.findings)
    return [
        { key: 'reason', kind: 'name', label: 'dismissed as', cell: (d) => dismissalText(d.reason), muted: true },
        {
            key: 'findings',
            kind: 'bar',
            label: 'findings',
            cell: (d) => d.findings,
            bar: (d) => barPercent(d.findings, findings),
        },
    ]
}

// What the per-PR table counts of each PR: how soon its first review came, with a bar against the slowest PR's, its
// feedback in the window, its approvals, its rounds and how many came before its first approval, what they cost, and
// how long it took from ready to merge.
function prColumns(rows: readonly ReviewsPullRequest[]): PullRequestColumn<ReviewsPullRequest>[] {
    const waits = rows.map((pr) => pr.first_review_hours)
    return [
        {
            key: 'first',
            label: 'first review',
            hint: `${PR_FIRST_HINT}; the bar against the slowest PR's`,
            cell: (pr) => hoursText(pr.first_review_hours),
            bar: (pr) => barPercent(pr.first_review_hours, waits),
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
        {
            key: 'approved',
            label: 'approved',
            hint: 'Its reviews that approved it',
            cell: (pr) => <span className={cn(pr.approved > 0 && 'text-status-done')}>{pr.approved}</span>,
        },
        { key: 'comments', label: 'comments', cell: (pr) => pr.comments, muted: true },
        { key: 'rounds', label: 'rounds', hint: 'Feedback plans that read it', cell: (pr) => pr.rounds },
        {
            key: 'to-approval',
            label: 'rounds to approval',
            hint: 'The feedback plans that read it and were approved before its first approval',
            cell: (pr) => pr.rounds_to_approval ?? '–',
            title: roundsToApprovalTitle,
        },
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
}
