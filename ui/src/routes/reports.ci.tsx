import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { ciReportQuery } from '@/api/queries'
import type {
    CiCheck,
    CiDay,
    CiFix,
    CiFixedCheck,
    CiKick,
    CiKickedPullRequest,
    CiPullRequest,
    CiReport,
} from '@/api/types'
import { Age } from '@/components/age'
import { ChartTable } from '@/components/chart-table'
import { Cost } from '@/components/cost'
import { DayChart, DayChartLegend } from '@/components/day-chart'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelSkeleton } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { PullRequestTable } from '@/components/pull-request-table'
import type { PullRequestColumn } from '@/components/pull-request-table'
import { ReadoutTiles } from '@/components/readout-tiles'
import type { ReadoutTile } from '@/components/readout-tiles'
import { ReportTable } from '@/components/report-table'
import type { ReportColumn } from '@/components/report-table'
import { RunLink } from '@/components/run-link'
import { Chip, Word } from '@/components/status'
import { TickLink } from '@/components/tick-link'
import { TicketLink } from '@/components/ticket-link'
import { Clipped } from '@/components/tip'
import { WindowToggle } from '@/components/window-toggle'
import type { DayChartSeries } from '@/lib/chart'
import {
    CI_WINDOWS,
    ciBars,
    ciFigures,
    ciLine,
    ciSeries,
    ciWindow,
    DEFAULT_CI_WINDOW,
    failureRate,
    failureShare,
    fixRateText,
    fixToGreenText,
    GREEN_FIRST_SERIES,
    greenFirstBars,
    greenFirstRateText,
    isFlaky,
    kickText,
    LIMITS_TEXT,
    FLAKY_RERUNS,
    nextHeadShare,
    nextHeadText,
    nextText,
    previousCiFigures,
    redSum,
    rerunsText,
    TO_GREEN_TEXT,
    toGreenText,
    VERDICTS_TEXT,
} from '@/lib/ci'
import { useClock } from '@/lib/clock'
import type { Clock } from '@/lib/clock'
import { counted } from '@/lib/descriptions'
import { pointsChange, readoutDelta, wholeChange } from '@/lib/readout-delta'
import { windowBefore, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { hoursText } from '@/lib/reports'
import { dayName, shareText } from '@/lib/spend'
import { cn } from '@/lib/utils'

interface CiSearch {
    days?: number | undefined
}

// What the page shows on every visit, on its title's hover: its description is the window's state.
const HELP = [
    'What CI did on the PRs canopy observed: each check by how often it went red, how often the next head fixed it,',
    'and how often a rerun on the same head passed; the heads green first time and the red checks by day; the resumes',
    'that fixed CI and what they cost; how long each PR stayed red; and the reruns canopy made or held.',
    LIMITS_TEXT,
].join(' ')

// What a column counts, in its name's tip.
const RATE_HINT = "Its red runs' share of its red and green ones"
const NEXT_HEAD_HINT = 'Of its red runs a run on a new head of the same PR followed, how many passed'
const FIXED_HINT = "The checks red on its PR's head when it started, and how each ran on the next head"
const RERUNS_HINT =
    'Its runs on a head it had been red on, with no new commit, and how many passed: ' +
    `flaky at ${FLAKY_RERUNS} that did`
// What the reruns panel says with kicks off and none made.
const KICKS_OFF =
    'Kicks are off: trust.max_flaky_kicks is 0, so a check a worker calls flaky waits for you to rerun it.'
const TO_GREEN_HINT = 'From the first red check on its PR to the first head with every check green'

// A fixed check's next run, in its state's color: green passed, red failed again, the rest muted.
const NEXT_TONE: Record<string, string> = {
    green: 'text-status-done',
    red: 'text-status-failed',
}

/**
 * What CI did over the last days on the PRs canopy observed: the share of heads green first time, each check's red
 * runs and how often a new head fixed it, the red checks by day, the fix-CI resumes, the flaky kicks against
 * `trust.max_flaky_kicks`, and the cooldown's refusals. The window is `?days=`, the week or 30 days; the week, the
 * default, needs no search.
 */
export const Route = createFileRoute('/reports/ci')({
    // Typed search params: a window the page does not offer is dropped, which reads as the week.
    validateSearch: (search: Record<string, unknown>): CiSearch => ({ days: ciWindow(search)?.days }),
    component: CiPage,
})

function CiPage() {
    const search = Route.useSearch()
    const shown: ReportWindow = search.days === undefined ? DEFAULT_CI_WINDOW : { days: search.days }
    const navigate = Route.useNavigate()
    const query = useQuery(ciReportQuery(shown.days ?? 7))
    const span = windowName(shown)
    const { data } = query
    // A read that failed with nothing on screen says so once, in the first panel, with Read again.
    const failed = data === undefined && query.error !== null
    return (
        <>
            <PageHeader
                title="CI"
                help={HELP}
                controls={
                    <WindowToggle
                        windows={CI_WINDOWS}
                        shown={shown}
                        testId="ci"
                        onPick={(picked) => {
                            void navigate({ search: { days: picked === DEFAULT_CI_WINDOW ? undefined : picked.days } })
                        }}
                    />
                }
                links={!failed && <ReadoutTiles tiles={ciTiles(data)} against={windowBefore(shown)} testId="ci" />}
            >
                {data === undefined ? (query.isPending ? 'reading the check runs' : null) : ciLine(data)}
            </PageHeader>
            <Panel data-testid="ci-checks">
                <PanelHeader label="Checks by name" />
                {data === undefined ? (
                    <PanelLoading query={query} className="min-h-40" />
                ) : (
                    <Checks checks={data.checks} span={span} />
                )}
            </Panel>
            {!failed && (
                <>
                    <Panel data-testid="ci-green-first">
                        <PanelHeader label="Green first time by day" />
                        {data === undefined ? (
                            <PanelSkeleton rows={6} className="min-h-72" />
                        ) : (
                            <GreenFirst found={data} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="ci-by-day">
                        <PanelHeader label="Red checks by day" />
                        {data === undefined ? (
                            <PanelSkeleton rows={6} className="min-h-72" />
                        ) : (
                            <ByDay found={data} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="ci-fixes">
                        <PanelHeader label="Fix-CI resumes">
                            <span className="readout text-xs text-muted-foreground" data-testid="ci-fix-rate">
                                {data === undefined ? '' : fixRateText(data.fixes)}
                            </span>
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton rows={4} className="min-h-32" />
                        ) : (
                            <Fixes fixes={data.fixes} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="ci-to-green">
                        <PanelHeader label="Time to green">
                            <span className="readout text-xs text-muted-foreground" data-testid="ci-to-green-median">
                                {data === undefined || data.median_hours_to_green === null
                                    ? ''
                                    : `median ${hoursText(data.median_hours_to_green)}`}
                            </span>
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton rows={4} className="min-h-32" />
                        ) : (
                            <ToGreen pullRequests={data.pull_requests} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="ci-reruns">
                        <PanelHeader label="Reruns">
                            <span className="readout text-xs text-muted-foreground" data-testid="ci-kick-limit">
                                {data === undefined ? '' : `trust.max_flaky_kicks = ${data.max_flaky_kicks}`}
                            </span>
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton rows={3} className="min-h-24" />
                        ) : (
                            <Reruns found={data} span={span} />
                        )}
                    </Panel>
                </>
            )}
        </>
    )
}

/**
 * The window's headline figures, each held in its place while the report is read, and each against the window
 * before's: more heads green first time, fewer red runs, and more fixes gone green are better. The median time to
 * green has no window before's to say against.
 */
function ciTiles(found: CiReport | undefined): ReadoutTile[] {
    const figures = found === undefined ? undefined : ciFigures(found)
    const before = found === undefined ? undefined : previousCiFigures(found.previous)
    return [
        {
            key: 'heads',
            label: 'PR heads',
            hint: 'The PR heads first checked in the window',
            value: figures?.heads,
            delta: readoutDelta(figures?.heads, before?.heads, wholeChange),
        },
        {
            key: 'green-first',
            label: 'green first time',
            hint: 'Of those heads, the share whose first run of every check was not red',
            value: figures === undefined ? undefined : shareText(figures.greenFirst),
            delta: readoutDelta(figures?.greenFirst, before?.greenFirst, pointsChange, 'up'),
        },
        {
            key: 'red',
            label: 'red runs',
            hint: 'The check runs that went red, every check',
            value: figures?.red,
            delta: readoutDelta(figures?.red, before?.red, wholeChange, 'down'),
        },
        {
            key: 'fixes',
            label: 'fix-CI resumes',
            hint: 'The resumes for CI that started',
            value: figures?.fixes,
            delta: readoutDelta(figures?.fixes, before?.fixes, wholeChange),
        },
        {
            key: 'fixes-green',
            label: 'went green',
            hint: 'Of those resumes, the ones whose every red check was green on the head after them',
            value: figures?.fixesGreen,
            delta: readoutDelta(figures?.fixesGreen, before?.fixesGreen, wholeChange, 'up'),
        },
        {
            key: 'red-spell',
            label: 'time to green',
            hint: "The median PR's time from its first red check to a head with every check green",
            value: found === undefined ? undefined : hoursText(found.median_hours_to_green),
        },
    ]
}

/**
 * Each check by name, the worst first: its failure rate as a bar in the failed state's color, since red is a state
 * here, its red runs and its runs beside it, how often its next run on a new head passed after a red one, and how
 * often a rerun on a head it had been red on passed, flaky past `FLAKY_RERUNS` without anyone's say-so. The table
 * sizes to its content. Under it, what counts as red, and what the page cannot see.
 */
function Checks({ checks, span }: { checks: CiCheck[]; span: string }) {
    return (
        <div className="flex flex-col gap-3 px-3 pb-3">
            {checks.length === 0 ? (
                <Empty size="panel">no check run was observed in these {span}</Empty>
            ) : (
                <ReportTable
                    rows={checks}
                    columns={CHECK_COLUMNS}
                    rowKey={(c) => c.name}
                    label="Checks by name"
                    className="max-h-96"
                    testId="ci-check-table"
                    rowTestId="ci-check"
                />
            )}
            <p className="text-xs text-muted-foreground" data-testid="ci-limits">
                {VERDICTS_TEXT} {LIMITS_TEXT}
            </p>
        </div>
    )
}

/**
 * Each day's PR heads first checked as a stacked bar, the ones green first time at the bottom, so a bad week shows
 * as a dip; the day's rate on hover, the legend under it, then the same numbers as a table. A window with no head
 * checked says so, in place of all three.
 */
function GreenFirst({ found, span }: { found: CiReport; span: string }) {
    const clock = useClock()
    if (found.per_day.every((day) => day.heads === 0)) {
        return <Empty size="panel">no PR head was checked in these {span}</Empty>
    }
    return (
        <div className="flex flex-col gap-4 p-3">
            {/* Measured afresh for each window: another count of bars is another pitch. */}
            <DayChart key={found.per_day.length} bars={greenFirstBars(found.per_day, clock)} testId="ci-green-first" />
            <DayChartLegend series={GREEN_FIRST_SERIES} testId="ci-green-first" />
            <ChartTable
                what={counted(found.per_day.length, 'day')}
                label="Green first time by day"
                className="max-h-60 overflow-x-auto"
            >
                <ReportTable
                    rows={found.per_day.toReversed()}
                    columns={greenFirstColumns(clock)}
                    rowKey={(day) => day.day}
                    label="Green first time by day"
                    scroll={false}
                    testId="ci-green-first-table"
                    rowTestId={(day) => `ci-green-day-${day.day}`}
                />
            </ChartTable>
        </div>
    )
}

/**
 * Each day's red check runs as a stacked bar, a series per check the server names apart and the rest as `other`, the
 * legend under it, then the same numbers as a table: the chart is for the eye, so a screen reader reads the table. A
 * window where nothing went red says so, in place of all three.
 */
function ByDay({ found, span }: { found: CiReport; span: string }) {
    const clock = useClock()
    if (found.per_day.every((day) => redSum(day) === 0)) {
        return <Empty size="panel">no check went red in these {span}</Empty>
    }
    const series = ciSeries(found.series)
    return (
        <div className="flex flex-col gap-4 p-3">
            {/* Measured afresh for each window: another count of bars is another pitch. */}
            <DayChart key={found.per_day.length} bars={ciBars(found.per_day, series, clock)} testId="ci" />
            <DayChartLegend series={series} testId="ci" />
            <ChartTable
                what={counted(found.per_day.length, 'day')}
                label="Red checks by day"
                className="max-h-60 overflow-x-auto"
            >
                <ReportTable
                    rows={found.per_day.toReversed()}
                    columns={redDayColumns(series, clock)}
                    rowKey={(day) => day.day}
                    label="Red checks by day"
                    scroll={false}
                    testId="ci-table"
                    rowTestId={(day) => `ci-day-${day.day}`}
                />
            </ChartTable>
        </div>
    )
}

/**
 * Each `resume` for `ci` that started in the window, the newest first, a retired `fix-ci` among them: the run, its
 * ticket, how it ended, the checks red on its PR's head when it started with how each one's first run on the next
 * head ended, how long its PR took to go green, what it cost, and when it started.
 */
function Fixes({ fixes, span }: { fixes: CiFix[]; span: string }) {
    if (fixes.length === 0) {
        return <Empty size="panel">no resume for CI started in these {span}</Empty>
    }
    return (
        <ReportTable
            rows={fixes}
            columns={FIX_COLUMNS}
            rowKey={(f) => String(f.run_id)}
            label="Fix-CI resumes"
            top
            testId="ci-fix-table"
            rowTestId={(f) => `ci-fix-${f.run_id}`}
        />
    )
}

/**
 * The checks table's columns: the check, its failure rate as a bar in the failed state's color, its red runs and its
 * runs, how often its next head went green, how often a rerun on the same head did, and the flaky chip after it.
 */
const CHECK_COLUMNS: ReportColumn<CiCheck>[] = [
    {
        key: 'check',
        kind: 'free',
        label: 'check',
        cell: (c) => <Clipped text={c.name} mono className="block font-mono" />,
    },
    {
        key: 'rate',
        kind: 'bar',
        label: 'failure rate',
        hint: RATE_HINT,
        cell: failureRate,
        bar: (c) => (failureShare(c) ?? 0) * 100,
        fill: 'bg-status-failed',
    },
    { key: 'red', kind: 'figure', label: 'red', cell: (c) => c.red, tone: (c) => c.red > 0 && 'text-status-failed' },
    { key: 'runs', kind: 'figure', label: 'runs', cell: (c) => c.runs, muted: true },
    {
        key: 'next',
        kind: 'bar',
        label: 'next head green',
        hint: NEXT_HEAD_HINT,
        cell: nextHeadText,
        bar: (c) => (nextHeadShare(c) ?? 0) * 100,
        muted: true,
    },
    { key: 'reruns', kind: 'figure', label: 'same-head reruns', hint: RERUNS_HINT, cell: rerunsText, muted: true },
    { key: 'flaky', kind: 'word', label: null, cell: (c) => isFlaky(c) && <Chip tone="blocked">flaky</Chip> },
]

/** A day table's first column: the day, or the hour in a day's window. */
function dayColumn(clock: Clock): ReportColumn<CiDay> {
    return {
        key: 'day',
        kind: 'name',
        label: 'day',
        cell: (day) => <span className="readout">{dayName(day, clock)}</span>,
    }
}

/** The green-first table's columns: the day, its heads, how many went green first time, and the rate. */
function greenFirstColumns(clock: Clock): ReportColumn<CiDay>[] {
    return [
        dayColumn(clock),
        { key: 'heads', kind: 'figure', label: 'heads', cell: (day) => day.heads, muted: true },
        { key: 'green', kind: 'figure', label: 'green first time', cell: (day) => day.green_first },
        { key: 'rate', kind: 'figure', label: 'rate', cell: greenFirstRateText, muted: true },
    ]
}

/** The red-by-day table's columns: the day, a column per series of the chart's, and the day's red runs. */
function redDayColumns(series: readonly DayChartSeries[], clock: Clock): ReportColumn<CiDay>[] {
    return [
        dayColumn(clock),
        ...series.map((s, i): ReportColumn<CiDay> => ({
            key: s.key,
            kind: 'figure',
            label: s.label,
            cell: (day) => day.red[i] ?? 0,
            muted: true,
        })),
        {
            key: 'red',
            kind: 'figure',
            label: 'red',
            cell: redSum,
            tone: (day) => redSum(day) > 0 && 'text-status-failed',
        },
    ]
}

/**
 * The fixes table's columns: the run, its ticket, how it ended, its red checks with how each ran on the next head,
 * how long its PR took to go green, what it cost, and when it started.
 */
const FIX_COLUMNS: ReportColumn<CiFix>[] = [
    {
        key: 'run',
        kind: 'name',
        label: 'run',
        cell: (f) => (
            <>
                <RunLink id={f.run_id} />
                {f.kind !== 'resume' && <Word word={f.kind} className="ml-2 font-mono text-muted-foreground" />}
            </>
        ),
    },
    { key: 'ticket', kind: 'word', label: 'ticket', cell: (f) => <TicketLink ticketKey={f.ticket_key} /> },
    {
        key: 'ended',
        kind: 'word',
        label: 'ended',
        cell: (f) => <Word word={f.status} className="font-mono" />,
        muted: true,
    },
    {
        key: 'checks',
        kind: 'free',
        label: 'checks, then the next head',
        hint: FIXED_HINT,
        cell: (f) => <FixedChecks checks={f.checks} />,
    },
    {
        key: 'green',
        kind: 'figure',
        label: 'to green',
        hint: TO_GREEN_HINT,
        cell: fixToGreenText,
        tone: (f) => fixToGreenText(f) === 'still red' && 'text-status-failed',
    },
    { key: 'spent', kind: 'figure', label: 'spent', cell: (f) => <Cost usd={f.cost_usd} />, muted: true },
    { key: 'started', kind: 'age', label: 'started', cell: (f) => <Age at={f.started_at} variant="ago" /> },
]

/** A fix's red checks, each with its PR and how its first run on the next head ended, in that state's color. */
function FixedChecks({ checks }: { checks: CiFixedCheck[] }) {
    if (checks.length === 0) {
        return <span className="text-muted-foreground">no red check observed when it started</span>
    }
    return (
        <ul className="flex flex-col gap-0.5">
            {checks.map((c) => (
                <li key={`${c.pr_url}:${c.name}`} className="flex min-w-0 items-center gap-2" data-testid="ci-fixed">
                    <PullRequestLink url={c.pr_url} className="shrink-0" />
                    <Clipped text={c.name} mono className="min-w-0 font-mono" />
                    <span className={cn('font-mono', NEXT_TONE[c.next ?? ''] ?? 'text-muted-foreground')}>
                        {nextText(c.next)}
                    </span>
                </li>
            ))}
        </ul>
    )
}

// What the kicks table counts of each PR: its kicks, the most one head of work had against the limit, and how many
// came back red.
function kickColumns(limit: number): PullRequestColumn<CiKickedPullRequest>[] {
    return [
        { key: 'kicks', label: 'kicks', cell: (pr) => pr.kicks },
        {
            key: 'most',
            label: 'most on a head',
            hint: 'The most kicks one head of work had, against trust.max_flaky_kicks',
            cell: (pr) => (limit === 0 ? pr.most : `${pr.most} of ${limit}`),
            muted: true,
        },
        {
            key: 'red',
            label: 'still red',
            hint: 'Its kicks whose check came back red',
            cell: (pr) => <span className={cn(pr.still_red > 0 && 'text-status-failed')}>{pr.still_red}</span>,
        },
    ]
}

// What the time-to-green table counts of each PR: when its spell of red began, and how long it lasted.
const TO_GREEN_COLUMNS: PullRequestColumn<CiPullRequest>[] = [
    {
        key: 'red-at',
        label: 'red since',
        hint: 'When its latest spell of red began: the first red check run canopy saw on it',
        cell: (pr) => (pr.red_at === null ? '–' : <Age at={pr.red_at} variant="ago" />),
        muted: true,
    },
    {
        key: 'took',
        label: 'to green',
        hint: TO_GREEN_HINT,
        cell: (pr) => {
            const text = toGreenText(pr)
            return <span className={cn('whitespace-nowrap', text === 'still red' && 'text-status-failed')}>{text}</span>
        },
    },
]

/**
 * Each PR with a check run in the window and how long it stayed red: those still red first, the oldest first, then the
 * slowest to go green, then those never red. Under it, how roughly it measures.
 */
function ToGreen({ pullRequests, span }: { pullRequests: CiPullRequest[]; span: string }) {
    if (pullRequests.length === 0) {
        return <Empty size="panel">no PR had a check run in these {span}</Empty>
    }
    return (
        <div className="flex flex-col">
            <PullRequestTable
                rows={pullRequests}
                columns={TO_GREEN_COLUMNS}
                label="Time to green by pull request"
                testId="ci-to-green"
            />
            <p className="px-3 pb-3 text-xs text-muted-foreground" data-testid="ci-to-green-caveat">
                {TO_GREEN_TEXT}
            </p>
        </div>
    )
}

/**
 * The window's reruns: the flaky kicks by PR against `trust.max_flaky_kicks`, then each kick whose check came back red;
 * with none made, one line saying so, or that kicks are off. Its foot is what the cooldown held while checks ran again.
 */
function Reruns({ found, span }: { found: CiReport; span: string }) {
    return (
        <div className="flex flex-col">
            <Kicks found={found} span={span} />
            <Cooldown found={found} span={span} />
        </div>
    )
}

/** The window's flaky kicks: by PR, then each kick whose check came back red; or one line when none was made. */
function Kicks({ found, span }: { found: CiReport; span: string }) {
    if (found.kicks.length === 0) {
        return (
            <p className="p-3 text-sm text-muted-foreground" data-testid="ci-kicks">
                {found.max_flaky_kicks === 0 ? KICKS_OFF : `No flaky kick in these ${span}.`}
            </p>
        )
    }
    const red = found.kicks.filter((k) => k.still_red.length > 0)
    return (
        <div className="flex flex-col" data-testid="ci-kicks">
            <PullRequestTable
                rows={found.kicked_pull_requests}
                columns={kickColumns(found.max_flaky_kicks)}
                label="Flaky kicks by pull request"
                testId="ci-kicked"
            />
            {red.length > 0 && (
                <div className="flex flex-col gap-1.5 border-t p-3" data-testid="ci-red-kicks">
                    <h3 className="panel-label">came back red</h3>
                    <ul className="flex flex-col gap-1 text-xs">
                        {red.map((k) => (
                            <RedKick key={`${k.run_id}:${k.repo}`} kick={k} limit={found.max_flaky_kicks} />
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )
}

/** A kick whose check came back red: the run that judged it flaky, its PR, its place against the limit, the checks. */
function RedKick({ kick, limit }: { kick: CiKick; limit: number }) {
    return (
        <li className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5" data-testid="ci-red-kick">
            <RunLink id={kick.run_id} />
            {kick.pr_url === null ? (
                <span className="font-mono text-muted-foreground">{kick.branch}</span>
            ) : (
                <PullRequestLink url={kick.pr_url} />
            )}
            <span className="font-mono text-muted-foreground">{kickText(kick, limit)}</span>
            <span className="font-mono text-status-failed">{kick.still_red.join(', ')}</span>
            <Age at={kick.kicked_at} variant="ago" className="ml-auto" />
        </li>
    )
}

/**
 * What the cooldown guard refused in the window, as the health page counts it, the reruns' foot under a hairline,
 * linking there rather than repeating.
 */
function Cooldown({ found, span }: { found: CiReport; span: string }) {
    const health = (
        <Link
            to="/reports/health"
            search={{ days: found.days === DEFAULT_CI_WINDOW.days ? undefined : found.days }}
            className="text-accent underline-offset-4 hover:underline"
        >
            Health
        </Link>
    )
    if (found.cooldown === null) {
        return (
            <p className="border-t p-3 text-xs text-muted-foreground" data-testid="ci-cooldown-line">
                The cooldown held no resume in these {span}. {health} has every guard&apos;s refusals.
            </p>
        )
    }
    const { decisions, ticks, last_tick: last } = found.cooldown
    return (
        <p className="border-t p-3 text-xs text-muted-foreground" data-testid="ci-cooldown-line">
            The cooldown held {decisions === 1 ? '1 resume' : `${decisions} resumes`} in{' '}
            {ticks === 1 ? '1 tick' : `${ticks} ticks`} while checks ran again, the latest <TickLink id={last} />.{' '}
            {health} has every guard&apos;s refusals.
        </p>
    )
}
