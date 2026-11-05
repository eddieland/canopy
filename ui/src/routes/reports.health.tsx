import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { healthReportQuery } from '@/api/queries'
import type {
    HealthAsk,
    HealthCause,
    HealthDay,
    HealthDuration,
    HealthFailure,
    HealthOutcome,
    HealthRefusal,
    HealthReport,
} from '@/api/types'
import { Age } from '@/components/age'
import { ChartTable } from '@/components/chart-table'
import { ChoreLink, ChoreRunLink } from '@/components/chore-link'
import { Cost } from '@/components/cost'
import { DayChart, DayChartLegend } from '@/components/day-chart'
import { LinkedText } from '@/components/linked-text'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll, PanelSkeleton } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { ReadoutTiles } from '@/components/readout-tiles'
import type { ReadoutTile } from '@/components/readout-tiles'
import { ReportTable } from '@/components/report-table'
import type { ReportColumn } from '@/components/report-table'
import { ReviewLink } from '@/components/review-link'
import { ListRow, RowList } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { Chip, RunDot, Word } from '@/components/status'
import { TaskLink, TaskRunLink } from '@/components/task-link'
import { TickLink } from '@/components/tick-link'
import { TicketLink } from '@/components/ticket-link'
import { Clipped, Hinted, Tipped } from '@/components/tip'
import { WindowToggle } from '@/components/window-toggle'
import { useClock } from '@/lib/clock'
import type { Clock } from '@/lib/clock'
import { counted } from '@/lib/descriptions'
import {
    binsText,
    countSum,
    dayRateText,
    DEFAULT_HEALTH_WINDOW,
    DURATION_BANDS,
    durationsByKind,
    HEALTH_SERIES,
    HEALTH_WINDOWS,
    healthBars,
    healthFigures,
    healthLine,
    healthWindow,
    minutesText,
    nearLimit,
    outcomeTree,
    previousHealthFigures,
} from '@/lib/health'
import type { OutcomeKind, OutcomeSort } from '@/lib/health'
import { pointsChange, readoutDelta, usdChange, wholeChange } from '@/lib/readout-delta'
import { windowBefore, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { dayName, shareText, unpricedText } from '@/lib/spend'
import { cn } from '@/lib/utils'

interface HealthSearch {
    days?: number | undefined
}

// What the page shows on every visit, on its title's hover: its description is the window's state.
const HELP =
    'How the runs of the last days ended, as canopy health reads them: each kind by how its runs ended and what ' +
    'that cost, the failed runs by day and by cause, the newest of them to open, what the guards refused the ' +
    'overseer, and how long each sort of run takes against its timeout. A failure is a run that did not do what it ' +
    'was started for: a worker that asked you a question, or one you stopped, did.'

// What the failed tile counts, on its name's tip.
const FAILED_HINT =
    'The runs that did not do what they were started for: a worker that asked you a question, or one you stopped, did'

// What a column counts, in its name's tip.
const ENDED_HINT = "A kind's failed runs' share of its ended ones, then how each sort's runs ended"
const OTHER_HINT = "Failures an agent's own summary explained, which never repeats, or that left no note"
const MEDIAN_HINT = 'The median run, in the warning color once it takes three quarters of its timeout'
const LIMIT_HINT = "The timeout the sort is held to, from [runtime], or the chore's own"
const SPREAD_HINT = "Its runs by their length's share of the timeout"

// Each kind as the outcomes table heads its rows: the series' names, so a kind reads alike in the table and the chart.
const KIND_NAME = Object.fromEntries(HEALTH_SERIES.map((s) => [s.key, s.label])) as Record<
    HealthOutcome['kind'],
    string
>

/**
 * How the last days' runs ended, as `canopy health` prints it: each kind's runs by sort and status with what they
 * cost, the failed runs by day, the newest failures, and what the guards refused. The window is `?days=`, the week or
 * 30 days; the week, the default, needs no search.
 */
export const Route = createFileRoute('/reports/health')({
    // Typed search params: a window the page does not offer is dropped, which reads as the week.
    validateSearch: (search: Record<string, unknown>): HealthSearch => ({ days: healthWindow(search)?.days }),
    component: HealthPage,
})

function HealthPage() {
    const search = Route.useSearch()
    const shown: ReportWindow = search.days === undefined ? DEFAULT_HEALTH_WINDOW : { days: search.days }
    const navigate = Route.useNavigate()
    const query = useQuery(healthReportQuery(shown.days ?? 7))
    const span = windowName(shown)
    const { data } = query
    // A read that failed with nothing on screen says so once, in the first panel, with Read again.
    const failed = data === undefined && query.error !== null
    return (
        <>
            <PageHeader
                title="Health"
                help={HELP}
                controls={
                    <WindowToggle
                        windows={HEALTH_WINDOWS}
                        shown={shown}
                        testId="health"
                        onPick={(picked) => {
                            void navigate({
                                search: { days: picked === DEFAULT_HEALTH_WINDOW ? undefined : picked.days },
                            })
                        }}
                    />
                }
                links={
                    !failed && <ReadoutTiles tiles={healthTiles(data)} against={windowBefore(shown)} testId="health" />
                }
            >
                {data === undefined ? (query.isPending ? 'reading how the runs ended' : null) : healthLine(data)}
            </PageHeader>
            <Panel data-testid="health-outcomes">
                <PanelHeader label="How runs ended" />
                {data === undefined ? (
                    <PanelLoading query={query} className="min-h-40" />
                ) : (
                    <Outcomes found={data} span={span} />
                )}
            </Panel>
            {!failed && (
                <>
                    <Panel data-testid="health-by-day">
                        <PanelHeader label="Failures by day" />
                        {data === undefined ? (
                            <PanelSkeleton rows={6} className="min-h-72" />
                        ) : (
                            <ByDay days={data.per_day} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="health-causes">
                        <PanelHeader label="Failures by cause" />
                        {data === undefined ? (
                            <PanelSkeleton rows={3} className="min-h-24" />
                        ) : (
                            <Causes causes={data.causes} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="health-failures">
                        <PanelHeader label="Newest failures">
                            <span className="readout text-xs text-muted-foreground">{data?.failures.length ?? ''}</span>
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton rows={5} className="min-h-40" />
                        ) : (
                            <Failures failures={data.failures} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="health-refusals">
                        <PanelHeader label="What the guards refused" />
                        {data === undefined ? (
                            <PanelSkeleton rows={3} className="min-h-24" />
                        ) : (
                            <Refusals refusals={data.refusals} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="health-durations">
                        <PanelHeader label="How long runs take" />
                        {data === undefined ? (
                            <PanelSkeleton rows={6} className="min-h-40" />
                        ) : (
                            <Durations durations={data.durations} span={span} />
                        )}
                    </Panel>
                </>
            )}
        </>
    )
}

/**
 * The window's headline figures, each held in its place while the report is read, and each against the window
 * before's: fewer failures, and a lower rate, are better; what they cost is spend, never colored.
 */
function healthTiles(found: HealthReport | undefined): ReadoutTile[] {
    const figures = found === undefined ? undefined : healthFigures(found)
    const before = found === undefined ? undefined : previousHealthFigures(found.previous)
    return [
        {
            key: 'runs',
            label: 'runs',
            hint: 'The runs that ended, of every kind',
            value: figures?.runs,
            delta: readoutDelta(figures?.runs, before?.runs, wholeChange),
        },
        {
            key: 'failed',
            label: 'failed',
            hint: FAILED_HINT,
            value: figures?.failed,
            delta: readoutDelta(figures?.failed, before?.failed, wholeChange, 'down'),
        },
        {
            key: 'rate',
            label: 'failure rate',
            hint: "The failed runs' share of the ended ones",
            value: figures === undefined ? undefined : shareText(figures.rate),
            delta: readoutDelta(figures?.rate, before?.rate, pointsChange, 'down'),
        },
        {
            key: 'failed-cost',
            label: 'failures cost',
            hint: 'What the failed runs cost, of those that reported a cost',
            value: figures === undefined ? undefined : <Cost usd={figures.failedUsd} />,
            delta: readoutDelta(figures?.failedUsd, before?.failedUsd, usdChange),
        },
    ]
}

/**
 * Each kind's ended runs as a group of rows, one table so the columns line up: the kind over its sorts, with its failed
 * runs' share of its ended ones as a bar in the failed state's color, the one state a bar here may wear, since it says
 * what is broken, then its runs and what they cost. Under it a row per sort, how its runs ended as chips, a failed
 * ending in the failed state's tone. Under the table, which runs reported no cost.
 */
function Outcomes({ found, span }: { found: HealthReport; span: string }) {
    if (found.outcomes.length === 0) {
        return <Empty size="panel">no run ended in these {span}</Empty>
    }
    return (
        <div className="flex flex-col gap-3 px-3 pb-3">
            <ReportTable
                groups={outcomeTree(found.outcomes).map((kind) => ({
                    key: kind.kind,
                    headRow: kind,
                    rows: kind.sorts,
                    testId: `health-kind-${kind.kind}`,
                }))}
                columns={OUTCOME_COLUMNS}
                rowKey={(line) => ('sorts' in line ? line.kind : line.what)}
                label="How runs ended"
                className="max-h-[28rem]"
                testId="health-outcome-table"
                rowTestId="health-outcome"
            />
            <p className="text-xs text-muted-foreground" data-testid="health-unpriced">
                {unpricedText(found.unpriced)}
            </p>
        </div>
    )
}

/**
 * The outcomes table's columns, for a kind's row and its sorts': the kind, or the sort; the kind's failed runs' share
 * of its ended ones, or how the sort's runs ended as chips, a failed ending in the failed state's tone; the runs; and
 * what they cost.
 */
const OUTCOME_COLUMNS: ReportColumn<OutcomeKind | OutcomeSort>[] = [
    {
        key: 'kind',
        kind: 'name',
        label: 'kind',
        cell: (line) =>
            'sorts' in line ? (
                KIND_NAME[line.kind]
            ) : (
                <span className="font-mono">
                    <Word word={line.what} />
                </span>
            ),
    },
    {
        key: 'ended',
        kind: 'bar',
        label: 'ended',
        hint: ENDED_HINT,
        cell: (line) =>
            'sorts' in line ? (
                shareText(failedShare(line))
            ) : (
                <span className="flex flex-wrap gap-1">
                    {line.statuses.map((st) => (
                        <Chip key={st.status} tone={st.failed ? 'failed' : 'plain'} className="gap-1.5">
                            <Word word={st.status} />
                            <span className="readout">{st.runs}</span>
                        </Chip>
                    ))}
                </span>
            ),
        bar: (line) => ('sorts' in line ? (failedShare(line) ?? 0) * 100 : 0),
        fill: 'bg-status-failed',
        tone: (line) => 'sorts' in line && line.failed > 0 && 'text-status-failed',
        across: (line) => !('sorts' in line),
    },
    { key: 'runs', kind: 'figure', label: 'runs', cell: (line) => line.runs },
    { key: 'spent', kind: 'figure', label: 'spent', cell: (line) => <Cost usd={line.costUsd} />, muted: true },
]

/** A kind's failed runs' share of its ended ones; null for a kind with none ended. */
function failedShare(kind: OutcomeKind): number | null {
    return kind.runs === 0 ? null : kind.failed / kind.runs
}

/**
 * Each day's failed runs as a stacked bar, by kind, with the legend under it, then each day's failed and ended runs
 * as a table: the chart is for the eye, so a screen reader reads the table. A window where nothing failed says so, in
 * place of all three.
 */
function ByDay({ days, span }: { days: HealthDay[]; span: string }) {
    const clock = useClock()
    if (days.every((day) => countSum(day.failed) === 0)) {
        return <Empty size="panel">no run failed in these {span}</Empty>
    }
    return (
        <div className="flex flex-col gap-4 p-3">
            {/* Measured afresh for each window: another count of bars is another pitch. */}
            <DayChart key={days.length} bars={healthBars(days, clock)} testId="health" />
            <DayChartLegend series={HEALTH_SERIES} testId="health" />
            <ChartTable what={counted(days.length, 'day')} label="Failures by day" className="max-h-60 overflow-x-auto">
                <ReportTable
                    rows={days.toReversed()}
                    columns={dayColumns(clock)}
                    rowKey={(day) => day.day}
                    label="Failures by day"
                    scroll={false}
                    testId="health-table"
                    rowTestId={(day) => `health-day-${day.day}`}
                />
            </ChartTable>
        </div>
    )
}

/** The newest failed runs, each a row: how it ended, its id, what it was about, its sort, its note, cost, and when. */
function Failures({ failures, span }: { failures: HealthFailure[]; span: string }) {
    if (failures.length === 0) {
        return <Empty size="panel">no run failed in these {span}</Empty>
    }
    return (
        <PanelScroll label="Newest failures" className="max-h-[32rem]">
            <RowList kind="failure" className="divide-y" data-testid="health-failure-list">
                {failures.map((f) => (
                    <ListRow key={`${f.kind}:${f.id}`} kind="failure" data-testid={`health-failure-${f.kind}-${f.id}`}>
                        <span className="flex min-w-0 items-center gap-1.5 font-mono text-xs text-status-failed">
                            <RunDot state="failed" />
                            <Word word={f.status} className="truncate" />
                        </span>
                        <span className="min-w-0 truncate">
                            <OwnLink failure={f} />
                        </span>
                        <span className="min-w-0 truncate">
                            <Subject failure={f} />
                        </span>
                        <span className="flex">
                            <Chip>{f.what}</Chip>
                        </span>
                        <Clipped text={f.note} className="min-w-0 text-xs text-muted-foreground">
                            <LinkedText text={f.note} />
                        </Clipped>
                        <Cost usd={f.cost_usd} className="text-right text-xs text-muted-foreground" />
                        <Age at={f.started_at} variant="ago" className="text-right" />
                    </ListRow>
                ))}
            </RowList>
        </PanelScroll>
    )
}

/** A failure's own id, opening its page: a tick, a worker's or a plan's run, a chore's run, a review, a task's run. */
function OwnLink({ failure }: { failure: HealthFailure }) {
    switch (failure.kind) {
        case 'overseer': {
            return <TickLink id={failure.id} />
        }
        case 'workers':
        case 'plans': {
            return <RunLink id={failure.id} />
        }
        case 'chores': {
            return failure.chore === null ? null : <ChoreRunLink name={failure.chore} id={failure.id} />
        }
        case 'reviews': {
            return <ReviewLink id={failure.id} />
        }
        case 'tasks': {
            return failure.task_id === null ? null : <TaskRunLink task={failure.task_id} run={failure.id} />
        }
        default: {
            return null
        }
    }
}

/** What a failure was about: a worker's or a plan's ticket, a review's PR, a task; nothing for a tick or a chore. */
function Subject({ failure }: { failure: HealthFailure }) {
    if (failure.ticket !== null) {
        return <TicketLink ticketKey={failure.ticket} />
    }
    if (failure.pr_url !== null) {
        return <PullRequestLink url={failure.pr_url} />
    }
    return failure.task_id === null ? null : <TaskLink id={failure.task_id} />
}

/**
 * Each cause of the window's failures, the most runs first: the harness's note, how many runs it explained, of which
 * kinds, and the newest of them to open. `other` is last: the failures an agent's own words explained, which never
 * repeat, so counting them alike would say nothing.
 */
function Causes({ causes, span }: { causes: HealthCause[]; span: string }) {
    if (causes.length === 0) {
        return <Empty size="panel">no run failed in these {span}</Empty>
    }
    return (
        <ReportTable
            rows={causes}
            columns={CAUSE_COLUMNS}
            rowKey={(c) => c.note ?? ''}
            label="Failures by cause"
            top
            testId="health-cause-table"
            rowTestId="health-cause"
        />
    )
}

/** The failures-by-day table's columns: the day, a column per kind, the day's failed runs, its ended ones, the rate. */
function dayColumns(clock: Clock): ReportColumn<HealthDay>[] {
    return [
        {
            key: 'day',
            kind: 'name',
            label: 'day',
            cell: (day) => <span className="readout">{dayName(day, clock)}</span>,
        },
        ...HEALTH_SERIES.map((series): ReportColumn<HealthDay> => ({
            key: series.key,
            kind: 'figure',
            label: series.label,
            cell: (day) => day.failed[series.key],
            muted: true,
        })),
        {
            key: 'failed',
            kind: 'figure',
            label: 'failed',
            cell: (day) => countSum(day.failed),
            tone: (day) => countSum(day.failed) > 0 && 'text-status-failed',
        },
        { key: 'ended', kind: 'figure', label: 'ended', cell: (day) => countSum(day.ended), muted: true },
        { key: 'rate', kind: 'figure', label: 'rate', cell: dayRateText, muted: true },
    ]
}

/**
 * The causes table's columns: the harness's note, cut to a line, or `other`; how many runs it explained, in the failed
 * color past one; their kinds; and the newest of them, and when it started.
 */
const CAUSE_COLUMNS: ReportColumn<HealthCause>[] = [
    {
        key: 'cause',
        kind: 'free',
        label: 'cause',
        cell: (c) =>
            c.note === null ? (
                <span className="text-muted-foreground">
                    <Hinted hint={OTHER_HINT}>other</Hinted>
                </span>
            ) : (
                <Clipped text={c.note} className="block">
                    <LinkedText text={c.note} />
                </Clipped>
            ),
    },
    {
        key: 'runs',
        kind: 'figure',
        label: 'runs',
        cell: (c) => c.runs,
        tone: (c) => c.note !== null && c.runs > 1 && 'text-status-failed',
    },
    {
        key: 'kinds',
        kind: 'word',
        label: 'kinds',
        cell: (c) => (
            <span className="flex gap-1">
                {c.kinds.map((k) => (
                    <Chip key={k}>{KIND_NAME[k]}</Chip>
                ))}
            </span>
        ),
    },
    { key: 'latest', kind: 'word', label: 'latest', cell: (c) => <OwnLink failure={c.latest} /> },
    { key: 'failed', kind: 'age', label: 'failed', cell: (c) => <Age at={c.latest.started_at} variant="ago" /> },
]

/**
 * Each guard that refused the overseer something, the most often first: how often, in how many ticks, and the latest,
 * on its own row, and under it what it refused most often, each with the run's kind, how often, and the latest tick
 * that asked. One ask refused tick after tick is the overseer stuck on it.
 */
function Refusals({ refusals, span }: { refusals: HealthRefusal[]; span: string }) {
    if (refusals.length === 0) {
        return <Empty size="panel">no guard refused anything in these {span}</Empty>
    }
    return (
        <ReportTable
            groups={refusals.map((r) => ({ key: r.guard, headRow: r, rows: r.asks, testId: 'health-refusal' }))}
            columns={REFUSAL_COLUMNS}
            rowKey={(line) =>
                'asks' in line
                    ? line.guard
                    : `${line.ticket ?? ''}:${line.chore ?? ''}:${line.pr ?? ''}:${line.kind ?? ''}`
            }
            label="What the guards refused"
            className="px-3 pb-3"
            testId="health-refusal-table"
            rowTestId="health-ask"
        />
    )
}

/**
 * The refusals table's columns, for a guard's row and its asks': the guard, or what the ask named; the run's kind it
 * asked for; how often it was refused; the latest tick that asked; and, for a guard, in how many ticks it refused.
 */
const REFUSAL_COLUMNS: ReportColumn<HealthRefusal | HealthAsk>[] = [
    {
        key: 'guard',
        kind: 'name',
        label: 'guard',
        cell: (line) => ('asks' in line ? <Word word={line.guard} /> : <AskSubject ask={line} />),
    },
    {
        key: 'kind',
        kind: 'word',
        label: 'kind',
        hint: 'The kind of run a dispatch asked for',
        cell: (line) =>
            'asks' in line ? null : line.kind === null ? (
                '–'
            ) : (
                <span className="font-mono">
                    <Word word={line.kind} />
                </span>
            ),
        muted: true,
    },
    { key: 'refused', kind: 'figure', label: 'refused', cell: (line) => line.decisions },
    { key: 'latest', kind: 'word', label: 'latest', cell: (line) => <TickLink id={line.last_tick} /> },
    {
        key: 'ticks',
        kind: 'figure',
        label: 'ticks',
        hint: 'In how many ticks the guard refused something',
        cell: (line) => ('asks' in line ? line.ticks : null),
        muted: true,
    },
]

/** What a refused ask named: its ticket, its chore, or its PR; a muted dash for an ask that named none. */
function AskSubject({ ask }: { ask: HealthAsk }) {
    if (ask.ticket !== null) {
        return <TicketLink ticketKey={ask.ticket} />
    }
    if (ask.chore !== null) {
        return <ChoreLink name={ask.chore} />
    }
    if (ask.pr !== null) {
        return <PullRequestLink url={ask.pr} />
    }
    return <span className="text-muted-foreground">–</span>
}

/**
 * How long each sort of run took, grouped by kind, against the timeout it is held to: its runs, the median, the
 * nine-in-ten, the longest, how many timed out, and a bar of its runs by their length's share of the timeout, the
 * legend under it. A median at three quarters of the timeout or more is in the warning color: a sort to give more
 * time, or less work.
 */
function Durations({ durations, span }: { durations: HealthDuration[]; span: string }) {
    if (durations.length === 0) {
        return <Empty size="panel">no run ended in these {span}</Empty>
    }
    return (
        <div className="flex flex-col gap-3 px-3 pb-3">
            <ReportTable
                groups={durationsByKind(durations).map((group) => ({
                    key: group.kind,
                    head: KIND_NAME[group.kind],
                    rows: group.sorts,
                    testId: `health-took-${group.kind}`,
                }))}
                columns={DURATION_COLUMNS}
                rowKey={(d) => d.what}
                label="How long runs take"
                className="max-h-[28rem]"
                testId="health-duration-table"
                rowTestId="health-duration"
            />
            <DayChartLegend series={DURATION_BANDS} testId="health-spread" />
        </div>
    )
}

/**
 * The durations table's columns, a sort's lengths against its timeout: its runs, the median, in the warning color
 * near the timeout, the nine-in-ten, the longest, the timeout, how many timed out, and its spread as a stacked bar.
 */
const DURATION_COLUMNS: ReportColumn<HealthDuration>[] = [
    {
        key: 'kind',
        kind: 'name',
        label: 'kind',
        cell: (d) => (
            <span className="font-mono">
                <Word word={d.what} />
            </span>
        ),
    },
    { key: 'runs', kind: 'figure', label: 'runs', cell: (d) => d.runs },
    {
        key: 'median',
        kind: 'figure',
        label: 'median',
        hint: MEDIAN_HINT,
        cell: (d) => minutesText(d.median_minutes),
        tone: (d) => nearLimit(d) && 'text-status-blocked',
    },
    {
        key: 'p90',
        kind: 'figure',
        label: 'p90',
        hint: 'Nine in ten of its runs took this long or less',
        cell: (d) => minutesText(d.p90_minutes),
        muted: true,
    },
    { key: 'longest', kind: 'figure', label: 'longest', cell: (d) => minutesText(d.longest_minutes), muted: true },
    {
        key: 'timeout',
        kind: 'figure',
        label: 'timeout',
        hint: LIMIT_HINT,
        cell: (d) => (d.limit_minutes === null ? '–' : minutesText(d.limit_minutes)),
        muted: true,
    },
    {
        key: 'timed-out',
        kind: 'figure',
        label: 'timed out',
        hint: 'Its runs that ended timeout',
        cell: (d) => d.timeouts,
        tone: (d) => (d.timeouts > 0 ? 'text-status-failed' : 'text-muted-foreground'),
    },
    {
        key: 'spread',
        kind: 'word',
        label: 'spread',
        hint: SPREAD_HINT,
        cell: (d) =>
            d.bins === null ? (
                <span className="text-muted-foreground">no timeout</span>
            ) : (
                <Spread bins={d.bins} runs={d.runs} />
            ),
    },
]

/**
 * A sort's runs by their length's share of its timeout, as a bar of segments, the quickest first, each as wide as its
 * share of the runs. The bar is the eye's; the same counts are in words for a screen reader, and in its tip.
 */
function Spread({ bins, runs }: { bins: NonNullable<HealthDuration['bins']>; runs: number }) {
    const text = binsText(bins)
    return (
        <Tipped fact={text}>
            <span className="sr-only">{text}</span>
            <span
                aria-hidden
                className="flex h-1.5 w-24 gap-px overflow-hidden rounded-full bg-surface-raised"
                data-testid="health-spread"
            >
                {DURATION_BANDS.filter((b) => bins[b.key] > 0).map((b) => (
                    <span
                        key={b.key}
                        className={cn('block h-full', b.fill)}
                        style={{ width: `${runs === 0 ? 0 : (bins[b.key] / runs) * 100}%` }}
                    />
                ))}
            </span>
        </Tipped>
    )
}
