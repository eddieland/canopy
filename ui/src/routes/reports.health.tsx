import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { healthReportQuery } from '@/api/queries'
import type { HealthDay, HealthFailure, HealthOutcome, HealthRefusal, HealthReport } from '@/api/types'
import { Age } from '@/components/age'
import { ChartTable } from '@/components/chart-table'
import { ChoreRunLink } from '@/components/chore-link'
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
import { Clipped } from '@/components/tip'
import { WindowToggle } from '@/components/window-toggle'
import { useClock } from '@/lib/clock'
import { counted } from '@/lib/descriptions'
import {
    countSum,
    DEFAULT_HEALTH_WINDOW,
    HEALTH_SERIES,
    HEALTH_WINDOWS,
    healthBars,
    healthFigures,
    healthLine,
    healthWindow,
    previousHealthFigures,
} from '@/lib/health'
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
    "that cost, the failed runs by day, the newest of them to open, and the overseer's asks a guard refused. A " +
    'failure is a run that did not do what it was started for: a worker that asked you a question, or one you ' +
    'stopped, did.'

// What the failed tile counts, on its name's tip.
const FAILED_HINT =
    'The runs that did not do what they were started for: a worker that asked you a question, or one you stopped, did'

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
 * Each kind's ended runs by sort and status, with what they cost, the kind named on its first row and a hairline over
 * each kind after the first; a failed status in the failed state's color. Under it, which runs reported no cost.
 */
function Outcomes({ found, span }: { found: HealthReport; span: string }) {
    if (found.outcomes.length === 0) {
        return <Empty size="panel">no run ended in these {span}</Empty>
    }
    return (
        <div className="flex flex-col gap-3 p-3">
            <PanelScroll label="How runs ended" className="max-h-96 overflow-x-auto">
                <table className="w-full border-collapse text-sm" data-testid="health-outcome-table">
                    <thead className="sticky top-0 bg-surface">
                        <tr className="text-right">
                            <th className="panel-label pb-1.5 text-left font-normal">kind</th>
                            <th className="panel-label pb-1.5 pl-3 text-left font-normal">sort</th>
                            <th className="panel-label pb-1.5 pl-3 text-left font-normal">ended</th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">runs</th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">spent</th>
                        </tr>
                    </thead>
                    <tbody className="font-mono text-xs">
                        {found.outcomes.map((o, i) => {
                            const first = i === 0 || found.outcomes[i - 1]?.kind !== o.kind
                            return (
                                <tr
                                    key={`${o.kind}:${o.what}:${o.status}`}
                                    className={cn('text-right', first && i > 0 && 'border-t')}
                                    data-testid="health-outcome"
                                >
                                    <th scope="row" className="py-0.5 text-left font-normal text-muted-foreground">
                                        {first ? KIND_NAME[o.kind] : ''}
                                    </th>
                                    <td className="py-0.5 pl-3 text-left">
                                        <Word word={o.what} />
                                    </td>
                                    <td
                                        className={cn(
                                            'py-0.5 pl-3 text-left',
                                            o.failed ? 'text-status-failed' : 'text-muted-foreground',
                                        )}
                                    >
                                        <Word word={o.status} />
                                    </td>
                                    <td className="readout pl-3">{o.runs}</td>
                                    <td className="readout pl-3 text-muted-foreground">
                                        <Cost usd={o.cost_usd} />
                                    </td>
                                </tr>
                            )
                        })}
                    </tbody>
                </table>
            </PanelScroll>
            <p className="text-xs text-muted-foreground" data-testid="health-unpriced">
                {unpricedText(found.unpriced)}
            </p>
        </div>
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

/** Each guard that refused the overseer something, the most often first: how often, in how many ticks, the latest. */
function Refusals({ refusals, span }: { refusals: HealthRefusal[]; span: string }) {
    if (refusals.length === 0) {
        return <Empty size="panel">no guard refused anything in these {span}</Empty>
    }
    return (
        <div className="p-3">
            <table className="w-full border-collapse text-sm" data-testid="health-refusal-table">
                <thead>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">guard</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">refused</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">ticks</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">latest</th>
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {refusals.map((r) => (
                        <tr key={r.guard} className="text-right" data-testid="health-refusal">
                            <th scope="row" className="py-0.5 text-left font-normal">
                                <Word word={r.guard} />
                            </th>
                            <td className="readout pl-3">{r.decisions}</td>
                            <td className="readout pl-3 text-muted-foreground">{r.ticks}</td>
                            <td className="pl-3">
                                <TickLink id={r.last_tick} />
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
