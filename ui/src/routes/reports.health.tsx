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
import { CellBar } from '@/components/cell-bar'
import { ChartTable } from '@/components/chart-table'
import { ChoreLink, ChoreRunLink } from '@/components/chore-link'
import { Cost } from '@/components/cost'
import { DayChart, DayChartLegend } from '@/components/day-chart'
import { LinkedText } from '@/components/linked-text'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll, PanelSkeleton } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { ReadoutTiles } from '@/components/readout-tiles'
import type { ReadoutTile } from '@/components/readout-tiles'
import { ReviewLink } from '@/components/review-link'
import { ListRow } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { Chip, RunDot, Word } from '@/components/status'
import { TaskLink, TaskRunLink } from '@/components/task-link'
import { TickLink } from '@/components/tick-link'
import { TicketLink } from '@/components/ticket-link'
import { Clipped, Hinted, Tipped } from '@/components/tip'
import { WindowToggle } from '@/components/window-toggle'
import { useClock } from '@/lib/clock'
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

// The column names of a table in a padded scrolling region: the head's cells take the padding.
const PADDED_HEAD = 'sticky top-0 bg-surface [&_th]:pt-3'

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
            <PanelScroll label="How runs ended" className="max-h-[28rem] overflow-x-auto">
                <table className="border-collapse text-sm" data-testid="health-outcome-table">
                    <thead className={PADDED_HEAD}>
                        <tr className="text-right">
                            <th className="panel-label pb-1.5 text-left font-normal">kind</th>
                            <th className="panel-label pb-1.5 pl-3 text-left font-normal">
                                <Hinted hint={ENDED_HINT}>ended</Hinted>
                            </th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">runs</th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">spent</th>
                        </tr>
                    </thead>
                    {outcomeTree(found.outcomes).map((kind, i) => (
                        <OutcomeGroup key={kind.kind} kind={kind} first={i === 0} />
                    ))}
                </table>
            </PanelScroll>
            <p className="text-xs text-muted-foreground" data-testid="health-unpriced">
                {unpricedText(found.unpriced)}
            </p>
        </div>
    )
}

/** A kind's rows of the outcomes tree: its own, with its failed share, runs, and spend, then a row per sort. */
function OutcomeGroup({ kind, first }: { kind: OutcomeKind; first: boolean }) {
    const share = kind.runs === 0 ? null : kind.failed / kind.runs
    return (
        <tbody className="font-mono text-xs" data-testid={`health-kind-${kind.kind}`}>
            <tr className="text-right">
                <th
                    scope="rowgroup"
                    className={cn('pb-0.5 text-left font-sans font-medium text-foreground', !first && 'pt-3')}
                >
                    {KIND_NAME[kind.kind]}
                </th>
                <td className={cn('pl-3 text-left', !first && 'pt-3')}>
                    <CellBar
                        percent={(share ?? 0) * 100}
                        fill="bg-status-failed"
                        valueClassName={cn('readout w-10 text-right', kind.failed > 0 && 'text-status-failed')}
                    >
                        {shareText(share)}
                    </CellBar>
                </td>
                <td className={cn('readout pl-3', !first && 'pt-3')}>{kind.runs}</td>
                <td className={cn('readout pl-3 text-muted-foreground', !first && 'pt-3')}>
                    <Cost usd={kind.costUsd} />
                </td>
            </tr>
            {kind.sorts.map((sort) => (
                <SortRow key={sort.what} sort={sort} />
            ))}
        </tbody>
    )
}

/** One sort's row: its name, how its runs ended as chips, the most first, then its runs and what they cost. */
function SortRow({ sort }: { sort: OutcomeSort }) {
    return (
        <tr className="text-right" data-testid="health-outcome">
            <th scope="row" className="py-0.5 pl-4 text-left font-normal">
                <Word word={sort.what} />
            </th>
            <td className="py-0.5 pl-3 text-left">
                <span className="flex flex-wrap gap-1">
                    {sort.statuses.map((st) => (
                        <Chip key={st.status} tone={st.failed ? 'failed' : 'plain'} className="gap-1.5">
                            <Word word={st.status} />
                            <span className="readout">{st.runs}</span>
                        </Chip>
                    ))}
                </span>
            </td>
            <td className="readout pl-3">{sort.runs}</td>
            <td className="readout pl-3 text-muted-foreground">
                <Cost usd={sort.costUsd} />
            </td>
        </tr>
    )
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
                <table className="border-collapse text-sm" data-testid="health-table">
                    <thead className="sticky top-0 bg-surface">
                        <tr className="text-right">
                            <th className="panel-label pb-1.5 text-left font-normal">day</th>
                            {HEALTH_SERIES.map((series) => (
                                <th key={series.key} className="panel-label pb-1.5 pl-3 font-normal">
                                    {series.label}
                                </th>
                            ))}
                            <th className="panel-label pb-1.5 pl-3 font-normal">failed</th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">ended</th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">rate</th>
                        </tr>
                    </thead>
                    <tbody className="font-mono text-xs">
                        {days.toReversed().map((day) => {
                            const failedRuns = countSum(day.failed)
                            return (
                                <tr key={day.day} className="text-right" data-testid={`health-day-${day.day}`}>
                                    <th scope="row" className="readout py-0.5 text-left font-normal">
                                        {dayName(day, clock)}
                                    </th>
                                    {HEALTH_SERIES.map((series) => (
                                        <td key={series.key} className="readout pl-3 text-muted-foreground">
                                            {day.failed[series.key]}
                                        </td>
                                    ))}
                                    <td className={cn('readout pl-3', failedRuns > 0 && 'text-status-failed')}>
                                        {failedRuns}
                                    </td>
                                    <td className="readout pl-3 text-muted-foreground">{countSum(day.ended)}</td>
                                    <td className="readout pl-3 text-muted-foreground">{dayRateText(day)}</td>
                                </tr>
                            )
                        })}
                    </tbody>
                </table>
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
            <ul className="divide-y" data-testid="health-failure-list">
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
            </ul>
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
        <PanelScroll label="Failures by cause" className="max-h-96 overflow-x-auto px-3 pb-3">
            <table className="w-full border-collapse text-sm" data-testid="health-cause-table">
                <thead className={PADDED_HEAD}>
                    <tr className="text-left whitespace-nowrap">
                        <th className="panel-label pb-1.5 font-normal">cause</th>
                        <th className="panel-label pb-1.5 pl-3 text-right font-normal">runs</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">kinds</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">latest</th>
                        <th className="panel-label pb-1.5 pl-3 text-right font-normal">failed</th>
                    </tr>
                </thead>
                <tbody className="text-xs">
                    {causes.map((c) => (
                        <tr key={c.note ?? ''} className="align-top" data-testid="health-cause">
                            {/* The cause takes the slack, cut to a line, so the figures after it keep their places. */}
                            <th scope="row" className="w-full max-w-0 py-0.5 text-left font-normal">
                                {c.note === null ? (
                                    <span className="text-muted-foreground">
                                        <Hinted hint={OTHER_HINT}>other</Hinted>
                                    </span>
                                ) : (
                                    <Clipped text={c.note} className="block">
                                        <LinkedText text={c.note} />
                                    </Clipped>
                                )}
                            </th>
                            <td
                                className={cn(
                                    'readout pl-3 text-right',
                                    c.note !== null && c.runs > 1 && 'text-status-failed',
                                )}
                            >
                                {c.runs}
                            </td>
                            <td className="pl-3 whitespace-nowrap">
                                <span className="flex gap-1">
                                    {c.kinds.map((k) => (
                                        <Chip key={k}>{KIND_NAME[k]}</Chip>
                                    ))}
                                </span>
                            </td>
                            <td className="pl-3 whitespace-nowrap">
                                <OwnLink failure={c.latest} />
                            </td>
                            <td className="pl-3 text-right whitespace-nowrap">
                                <Age at={c.latest.started_at} variant="ago" />
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}

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
        <div className="px-3 pb-3">
            <table className="border-collapse text-sm" data-testid="health-refusal-table">
                <thead className="[&_th]:pt-3">
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">guard</th>
                        <th className="panel-label pb-1.5 pl-3 text-left font-normal">
                            <Hinted hint="The kind of run a dispatch asked for">kind</Hinted>
                        </th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">refused</th>
                        <th className="panel-label pb-1.5 pl-3 text-left font-normal">latest</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">
                            <Hinted hint="In how many ticks the guard refused something">ticks</Hinted>
                        </th>
                    </tr>
                </thead>
                {refusals.map((r, i) => (
                    <tbody key={r.guard} className="font-mono text-xs" data-testid="health-refusal">
                        <tr className="text-right">
                            <th
                                scope="rowgroup"
                                colSpan={2}
                                className={cn(
                                    'pb-0.5 text-left font-sans font-medium text-foreground',
                                    i > 0 && 'pt-3',
                                )}
                            >
                                <Word word={r.guard} />
                            </th>
                            <td className={cn('readout pl-3', i > 0 && 'pt-3')}>{r.decisions}</td>
                            <td className={cn('pl-3 text-left', i > 0 && 'pt-3')}>
                                <TickLink id={r.last_tick} />
                            </td>
                            <td className={cn('readout pl-3 text-muted-foreground', i > 0 && 'pt-3')}>{r.ticks}</td>
                        </tr>
                        {r.asks.map((a) => (
                            <tr
                                key={`${a.ticket ?? ''}:${a.chore ?? ''}:${a.pr ?? ''}:${a.kind ?? ''}`}
                                className="text-right"
                                data-testid="health-ask"
                            >
                                <th scope="row" className="py-0.5 pl-4 text-left font-normal">
                                    <AskSubject ask={a} />
                                </th>
                                <td className="pl-3 text-left text-muted-foreground">
                                    {a.kind === null ? '–' : <Word word={a.kind} />}
                                </td>
                                <td className="readout pl-3">{a.decisions}</td>
                                <td colSpan={2} className="pl-3 text-left">
                                    <TickLink id={a.last_tick} />
                                </td>
                            </tr>
                        ))}
                    </tbody>
                ))}
            </table>
        </div>
    )
}

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
            <PanelScroll label="How long runs take" className="max-h-[28rem] overflow-x-auto">
                <table className="border-collapse text-sm" data-testid="health-duration-table">
                    <thead className={PADDED_HEAD}>
                        <tr className="text-right">
                            <th className="panel-label pb-1.5 text-left font-normal">kind</th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">runs</th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">
                                <Hinted hint={MEDIAN_HINT}>median</Hinted>
                            </th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">
                                <Hinted hint="Nine in ten of its runs took this long or less">p90</Hinted>
                            </th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">longest</th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">
                                <Hinted hint={LIMIT_HINT}>timeout</Hinted>
                            </th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">
                                <Hinted hint="Its runs that ended timeout">timed out</Hinted>
                            </th>
                            <th className="panel-label pb-1.5 pl-3 text-left font-normal">
                                <Hinted hint={SPREAD_HINT}>spread</Hinted>
                            </th>
                        </tr>
                    </thead>
                    {durationsByKind(durations).map((group, i) => (
                        <tbody key={group.kind} className="font-mono text-xs" data-testid={`health-took-${group.kind}`}>
                            <tr>
                                <th
                                    scope="rowgroup"
                                    colSpan={8}
                                    className={cn(
                                        'pb-0.5 text-left font-sans font-medium text-foreground',
                                        i > 0 && 'pt-3',
                                    )}
                                >
                                    {KIND_NAME[group.kind]}
                                </th>
                            </tr>
                            {group.sorts.map((d) => (
                                <DurationRow key={d.what} duration={d} />
                            ))}
                        </tbody>
                    ))}
                </table>
            </PanelScroll>
            <DayChartLegend series={DURATION_BANDS} testId="health-spread" />
        </div>
    )
}

/** One sort's row of the durations table: its lengths against its timeout, and its spread as a stacked bar. */
function DurationRow({ duration: d }: { duration: HealthDuration }) {
    const limit = d.limit_minutes ?? null
    return (
        <tr className="text-right" data-testid="health-duration">
            <th scope="row" className="py-0.5 pl-4 text-left font-normal">
                <Word word={d.what} />
            </th>
            <td className="readout pl-3">{d.runs}</td>
            <td className={cn('readout pl-3', nearLimit(d) && 'text-status-blocked')}>
                {minutesText(d.median_minutes)}
            </td>
            <td className="readout pl-3 text-muted-foreground">{minutesText(d.p90_minutes)}</td>
            <td className="readout pl-3 text-muted-foreground">{minutesText(d.longest_minutes)}</td>
            <td className="readout pl-3 text-muted-foreground">{limit === null ? '–' : minutesText(limit)}</td>
            <td className={cn('readout pl-3', d.timeouts > 0 ? 'text-status-failed' : 'text-muted-foreground')}>
                {d.timeouts}
            </td>
            <td className="pl-3 text-left">
                {d.bins === null ? (
                    <span className="text-muted-foreground">no timeout</span>
                ) : (
                    <Spread bins={d.bins} runs={d.runs} />
                )}
            </td>
        </tr>
    )
}

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
