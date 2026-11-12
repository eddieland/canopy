import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { connectorsReportQuery } from '@/api/queries'
import type {
    ConnectorsDay,
    ConnectorsRefusal,
    ConnectorsReport,
    ConnectorsRun,
    ConnectorsSource,
    ConnectorsSourceRuns,
} from '@/api/types'
import { Age } from '@/components/age'
import { ChartTable } from '@/components/chart-table'
import { DayChart, DayChartLegend } from '@/components/day-chart'
import { LinkedText } from '@/components/linked-text'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelSkeleton } from '@/components/panel'
import { ReadoutTiles } from '@/components/readout-tiles'
import type { ReadoutTile } from '@/components/readout-tiles'
import { ReportTable } from '@/components/report-table'
import type { ReportColumn } from '@/components/report-table'
import { Chip, Word } from '@/components/status'
import { TickLink } from '@/components/tick-link'
import { Clipped } from '@/components/tip'
import { WindowToggle } from '@/components/window-toggle'
import type { DayChartSeries } from '@/lib/chart'
import { useClock } from '@/lib/clock'
import type { Clock } from '@/lib/clock'
import {
    connectorBars,
    connectorSeries,
    CONNECTORS_WINDOWS,
    connectorsFigures,
    connectorsLine,
    connectorsWindow,
    COUNTS_TEXT,
    DEFAULT_CONNECTORS_WINDOW,
    freshnessText,
    linesText,
    previousConnectorsFigures,
    retentionText,
    shortRuns,
    shortShareText,
    shortSum,
} from '@/lib/connectors'
import { counted } from '@/lib/descriptions'
import { minutesText } from '@/lib/health'
import { pointsChange, readoutDelta, wholeChange } from '@/lib/readout-delta'
import { windowBefore, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { dayName, shareText } from '@/lib/spend'

interface ConnectorsSearch {
    days?: number | undefined
}

// What the page shows on every visit, on its title's hover: its description is the window's state.
const HELP =
    'How the connectors read: each source now, as canopy status names it, with how its latest run ended and how old ' +
    "what it observed is; then its runs over the window, a tick's and each poll's between ticks, by how they ended " +
    'and how long they took against its timeout; the runs that read less than asked by day, and the newest of them ' +
    'with what they missed; and the lines canopy refused. The page runs no source and changes no config.'

// What a column counts, in its name's tip.
const SHORT_HINT = 'Its runs that read less than asked, partial and failed together, as a share of its runs'
const MEDIAN_HINT = "The median run, in the warning color once it takes three quarters of the source's timeout"
const LIMIT_HINT = "The source's timeout_minutes, as configured now"
const OLDEST_HINT =
    'How old the oldest observation of what its latest run asked about is; stale past connect.max_age_minutes'
const MISSED_HINT = "The harness's words for what the run missed, then the connector's own, from its stderr"

// A run's ending, in its state's tone: a run that recorded nothing failed, one that read some of it is amber.
const STATUS_TONE = { ok: 'plain', partial: 'blocked', failed: 'failed' } as const

/**
 * How the connectors read: each source now, its runs over the last days by how they ended and how long they took,
 * those that read less than asked by day and the newest of them, and the lines canopy refused. The window is
 * `?days=`, the week or 30 days; the week, the default, needs no search.
 */
export const Route = createFileRoute('/reports/connectors')({
    // Typed search params: a window the page does not offer is dropped, which reads as the week.
    validateSearch: (search: Record<string, unknown>): ConnectorsSearch => ({ days: connectorsWindow(search)?.days }),
    component: ConnectorsPage,
})

function ConnectorsPage() {
    const search = Route.useSearch()
    const shown: ReportWindow = search.days === undefined ? DEFAULT_CONNECTORS_WINDOW : { days: search.days }
    const navigate = Route.useNavigate()
    const query = useQuery(connectorsReportQuery(shown.days ?? 7))
    const span = windowName(shown)
    const { data } = query
    // A read that failed with nothing on screen says so once, in the first panel, with Read again.
    const failed = data === undefined && query.error !== null
    return (
        <>
            <PageHeader
                title="Connectors"
                help={HELP}
                controls={
                    <WindowToggle
                        windows={CONNECTORS_WINDOWS}
                        shown={shown}
                        testId="connectors"
                        onPick={(picked) => {
                            void navigate({
                                search: { days: picked === DEFAULT_CONNECTORS_WINDOW ? undefined : picked.days },
                            })
                        }}
                    />
                }
                links={
                    !failed && (
                        <ReadoutTiles tiles={connectorsTiles(data)} against={windowBefore(shown)} testId="connectors" />
                    )
                }
            >
                {data === undefined ? (query.isPending ? "reading the sources' runs" : null) : connectorsLine(data)}
            </PageHeader>
            <Panel data-testid="connectors-sources">
                <PanelHeader label="Sources now">
                    <span className="readout text-xs text-muted-foreground" data-testid="connectors-max-age">
                        {data === undefined ? '' : `connect.max_age_minutes = ${data.max_age_minutes}`}
                    </span>
                </PanelHeader>
                {data === undefined ? (
                    <PanelLoading query={query} className="min-h-24" />
                ) : (
                    <Sources sources={data.sources} />
                )}
            </Panel>
            {!failed && (
                <>
                    <Panel data-testid="connectors-runs">
                        <PanelHeader label="Runs by source" />
                        {data === undefined ? (
                            <PanelSkeleton rows={3} className="min-h-32" />
                        ) : (
                            <Runs found={data} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="connectors-by-day">
                        <PanelHeader label="Read less than asked by day" />
                        {data === undefined ? (
                            <PanelSkeleton rows={6} className="min-h-72" />
                        ) : (
                            <ByDay found={data} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="connectors-newest">
                        <PanelHeader label="Newest runs that read less than asked">
                            <span className="readout text-xs text-muted-foreground">{data?.newest.length ?? ''}</span>
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton rows={4} className="min-h-32" />
                        ) : (
                            <Newest runs={data.newest} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="connectors-refused">
                        <PanelHeader label="Refused lines" />
                        {data === undefined ? (
                            <PanelSkeleton rows={2} className="min-h-24" />
                        ) : (
                            <Refused refusals={data.refusals} span={span} />
                        )}
                    </Panel>
                </>
            )}
        </>
    )
}

/**
 * The window's headline figures, each held in its place while the report is read, and each against the window
 * before's: fewer runs that read less than asked, a lower share of them, and fewer refused lines are better.
 */
function connectorsTiles(found: ConnectorsReport | undefined): ReadoutTile[] {
    const figures = found === undefined ? undefined : connectorsFigures(found)
    const before = found === undefined ? undefined : previousConnectorsFigures(found.previous)
    return [
        {
            key: 'runs',
            label: 'runs',
            hint: "The sources' runs, a tick's and each poll's between ticks",
            value: figures?.runs,
            delta: readoutDelta(figures?.runs, before?.runs, wholeChange),
        },
        {
            key: 'short',
            label: 'read less than asked',
            hint: 'The runs that ended partial or failed',
            value: figures?.short,
            delta: readoutDelta(figures?.short, before?.short, wholeChange, 'down'),
        },
        {
            key: 'rate',
            label: 'short rate',
            hint: "Those runs' share of every run",
            value: figures === undefined ? undefined : shareText(figures.rate),
            delta: readoutDelta(figures?.rate, before?.rate, pointsChange, 'down'),
        },
        {
            key: 'refused',
            label: 'refused lines',
            hint: 'The lines canopy refused of what the sources printed, each leaving its subject not read whole',
            value: figures?.refused,
            delta: readoutDelta(figures?.refused, before?.refused, wholeChange, 'down'),
        },
    ]
}

/** Each source that reads, in the order a tick runs them, as `canopy status` names it. */
function Sources({ sources }: { sources: ConnectorsSource[] }) {
    if (sources.length === 0) {
        return <Empty size="panel">no source reads</Empty>
    }
    return (
        <ReportTable
            rows={sources}
            columns={SOURCE_COLUMNS}
            rowKey={(s) => s.name}
            label="Sources now"
            testId="connectors-source-table"
            rowTestId={(s) => `connectors-source-${s.name}`}
        />
    )
}

/**
 * The sources table's columns: the source, its kind, how its latest run ended and when, the tick that made it or a
 * poll, how old its oldest observation is, what else its freshness says, and a stale chip.
 */
const SOURCE_COLUMNS: ReportColumn<ConnectorsSource>[] = [
    { key: 'source', kind: 'name', label: 'source', cell: (s) => <span className="font-mono">{s.name}</span> },
    { key: 'kind', kind: 'word', label: 'kind', cell: (s) => <Word word={s.kind} />, muted: true },
    {
        key: 'latest',
        kind: 'word',
        label: 'latest run',
        cell: (s) =>
            s.status === null ? (
                <span className="text-muted-foreground">never ran</span>
            ) : (
                <Chip tone={STATUS_TONE[s.status]}>{s.status}</Chip>
            ),
    },
    {
        key: 'ended',
        kind: 'age',
        label: 'ended',
        cell: (s) => (s.ended_at === null ? '–' : <Age at={s.ended_at} variant="ago" />),
    },
    { key: 'by', kind: 'word', label: 'by', cell: (s) => <MadeBy run={s.run_id} tick={s.tick_id} />, muted: true },
    {
        key: 'oldest',
        kind: 'age',
        label: 'oldest observation',
        hint: OLDEST_HINT,
        cell: (s) => (s.oldest_at === null ? '–' : <Age at={s.oldest_at} />),
        tone: (s) => s.stale && 'text-status-blocked',
    },
    {
        key: 'fresh',
        kind: 'free',
        label: null,
        cell: (s) => (
            <span className="flex items-center gap-2">
                {s.stale && <Chip tone="blocked">stale</Chip>}
                <span className="text-muted-foreground">{freshnessText(s)}</span>
            </span>
        ),
    },
]

/** Who made a run: its tick, or the loop's poll between ticks; nothing for a source that never ran. */
function MadeBy({ run, tick }: { run: number | null; tick: number | null }) {
    if (run === null) {
        return null
    }
    return tick === null ? <span className="text-muted-foreground">poll</span> : <TickLink id={tick} />
}

/**
 * Each source that ran in the window: its runs, a tick's and each poll's, how they ended, the share that read less
 * than asked as a bar in the failed state's color, its median and nine-in-ten lengths against its timeout, and the
 * lines it recorded and canopy refused. Under it, what a run counts and how far back the journal reaches.
 */
function Runs({ found, span }: { found: ConnectorsReport; span: string }) {
    return (
        <div className="flex flex-col gap-3 px-3 pb-3">
            {found.runs.length === 0 ? (
                <Empty size="panel">no source ran in these {span}</Empty>
            ) : (
                <ReportTable
                    rows={found.runs}
                    columns={RUN_COLUMNS}
                    rowKey={(s) => s.source}
                    label="Runs by source"
                    className="max-h-96"
                    testId="connectors-run-table"
                    rowTestId={(s) => `connectors-runs-${s.source}`}
                />
            )}
            <p className="text-xs text-muted-foreground" data-testid="connectors-limits">
                {COUNTS_TEXT} {retentionText(found)}
            </p>
        </div>
    )
}

/** Whether a source's median run takes three quarters of its timeout or more. */
function nearTimeout(s: ConnectorsSourceRuns): boolean {
    return s.limit_minutes !== null && s.limit_minutes > 0 && s.median_minutes >= 0.75 * s.limit_minutes
}

/**
 * The runs table's columns: the source, its runs, a tick's and each poll's, how many ended each way, the share that
 * read less than asked, its median and p90 lengths and its timeout, and the lines it recorded and canopy refused.
 */
const RUN_COLUMNS: ReportColumn<ConnectorsSourceRuns>[] = [
    { key: 'source', kind: 'name', label: 'source', cell: (s) => <span className="font-mono">{s.source}</span> },
    { key: 'runs', kind: 'figure', label: 'runs', cell: (s) => s.runs },
    { key: 'ticks', kind: 'figure', label: 'ticks', hint: "A tick's runs", cell: (s) => s.ticks, muted: true },
    {
        key: 'polls',
        kind: 'figure',
        label: 'polls',
        hint: "The loop's polls between ticks, which raise nothing on the attention list",
        cell: (s) => s.polls,
        muted: true,
    },
    { key: 'ok', kind: 'figure', label: 'ok', cell: (s) => s.ok, muted: true },
    {
        key: 'partial',
        kind: 'figure',
        label: 'partial',
        cell: (s) => s.partial,
        tone: (s) => s.partial > 0 && 'text-status-blocked',
    },
    {
        key: 'failed',
        kind: 'figure',
        label: 'failed',
        cell: (s) => s.failed,
        tone: (s) => s.failed > 0 && 'text-status-failed',
    },
    {
        key: 'short',
        kind: 'bar',
        label: 'read less',
        hint: SHORT_HINT,
        cell: shortShareText,
        bar: (s) => (s.runs === 0 ? 0 : (shortRuns(s) / s.runs) * 100),
        fill: 'bg-status-failed',
    },
    {
        key: 'median',
        kind: 'figure',
        label: 'median',
        hint: MEDIAN_HINT,
        cell: (s) => minutesText(s.median_minutes),
        tone: (s) => nearTimeout(s) && 'text-status-blocked',
    },
    {
        key: 'p90',
        kind: 'figure',
        label: 'p90',
        hint: 'Nine in ten of its runs took this long or less',
        cell: (s) => minutesText(s.p90_minutes),
        muted: true,
    },
    {
        key: 'timeout',
        kind: 'figure',
        label: 'timeout',
        hint: LIMIT_HINT,
        cell: (s) => (s.limit_minutes === null ? '–' : minutesText(s.limit_minutes)),
        muted: true,
    },
    {
        key: 'recorded',
        kind: 'word',
        label: 'recorded',
        hint: 'The lines its runs recorded, by kind',
        cell: (s) => linesText(s.recorded),
        muted: true,
    },
    {
        key: 'refused',
        kind: 'word',
        label: 'refused',
        hint: 'The lines canopy refused of its runs, by kind',
        cell: (s) => linesText(s.refused),
        tone: (s) => Object.keys(s.refused).length > 0 && 'text-status-failed',
    },
]

/**
 * Each day's runs that read less than asked as a stacked bar, a series per source, the legend under it, then the same
 * numbers as a table: the chart is for the eye, so a screen reader reads the table. A window where every run read
 * everything says so, in place of all three.
 */
function ByDay({ found, span }: { found: ConnectorsReport; span: string }) {
    const clock = useClock()
    if (found.per_day.every((day) => shortSum(day) === 0)) {
        return <Empty size="panel">every run read everything it was asked in these {span}</Empty>
    }
    const series = connectorSeries(found.runs)
    return (
        <div className="flex flex-col gap-4 p-3">
            {/* Measured afresh for each window: another count of bars is another pitch. */}
            <DayChart
                key={found.per_day.length}
                bars={connectorBars(found.per_day, series, clock)}
                testId="connectors"
            />
            <DayChartLegend series={series} testId="connectors" />
            <ChartTable
                what={counted(found.per_day.length, 'day')}
                label="Read less than asked by day"
                className="max-h-60 overflow-x-auto"
            >
                <ReportTable
                    rows={found.per_day.toReversed()}
                    columns={dayColumns(series, clock)}
                    rowKey={(day) => day.day}
                    label="Read less than asked by day"
                    scroll={false}
                    testId="connectors-table"
                    rowTestId={(day) => `connectors-day-${day.day}`}
                />
            </ChartTable>
        </div>
    )
}

/** The by-day table's columns: the day, a column per source, and the day's runs that read less than asked. */
function dayColumns(series: readonly DayChartSeries[], clock: Clock): ReportColumn<ConnectorsDay>[] {
    return [
        {
            key: 'day',
            kind: 'name',
            label: 'day',
            cell: (day) => <span className="readout">{dayName(day, clock)}</span>,
        },
        ...series.map((s, i): ReportColumn<ConnectorsDay> => ({
            key: s.key,
            kind: 'figure',
            label: s.label,
            cell: (day) => day.short[i] ?? 0,
            muted: true,
        })),
        {
            key: 'short',
            kind: 'figure',
            label: 'read less',
            cell: shortSum,
            tone: (day) => shortSum(day) > 0 && 'text-status-failed',
        },
    ]
}

/**
 * The newest runs that read less than asked, the newest first: how it ended, its source, the tick that made it or a
 * poll, how long it ran, what it missed in the harness's words with the connector's stderr under it, and when.
 */
function Newest({ runs, span }: { runs: ConnectorsRun[]; span: string }) {
    if (runs.length === 0) {
        return <Empty size="panel">every run read everything it was asked in these {span}</Empty>
    }
    return (
        <ReportTable
            rows={runs}
            columns={NEWEST_COLUMNS}
            rowKey={(r) => String(r.id)}
            label="Newest runs that read less than asked"
            top
            testId="connectors-newest-table"
            rowTestId={(r) => `connectors-run-${r.id}`}
        />
    )
}

/** The newest runs' columns: how it ended, its source, who made it, how long it ran, what it missed, and when. */
const NEWEST_COLUMNS: ReportColumn<ConnectorsRun>[] = [
    {
        key: 'status',
        kind: 'word',
        label: 'ended',
        cell: (r) => <Chip tone={STATUS_TONE[r.status]}>{r.status}</Chip>,
    },
    { key: 'source', kind: 'word', label: 'source', cell: (r) => <span className="font-mono">{r.source}</span> },
    { key: 'by', kind: 'word', label: 'by', cell: (r) => <MadeBy run={r.id} tick={r.tick_id} />, muted: true },
    { key: 'took', kind: 'figure', label: 'took', cell: (r) => minutesText(r.minutes), muted: true },
    {
        key: 'missed',
        kind: 'free',
        label: 'what it missed',
        hint: MISSED_HINT,
        cell: (r) => <Missed run={r} />,
    },
    { key: 'started', kind: 'age', label: 'started', cell: (r) => <Age at={r.started_at} variant="ago" /> },
]

/**
 * What a run missed, in the harness's words, and under it the tail of the connector's stderr where it says more: the
 * connector's own words, untrusted, so text, each cut to a line and whole on hover.
 */
function Missed({ run }: { run: ConnectorsRun }) {
    const said = run.stderr !== '' && !run.missed.includes(run.stderr)
    return (
        <span className="flex min-w-0 flex-col gap-0.5">
            <Clipped text={run.missed} className="block">
                <LinkedText text={run.missed} />
            </Clipped>
            {said && (
                <Clipped text={run.stderr} mono className="block font-mono text-xs text-muted-foreground">
                    <LinkedText text={run.stderr} />
                </Clipped>
            )}
        </span>
    )
}

/**
 * The lines canopy refused, by source and kind of line, the most first: a refused line leaves its subject not read
 * whole, so a kind refused run after run is a connector and canopy disagreeing on the contract.
 */
function Refused({ refusals, span }: { refusals: ConnectorsRefusal[]; span: string }) {
    if (refusals.length === 0) {
        return <Empty size="panel">canopy refused no line in these {span}</Empty>
    }
    return (
        <ReportTable
            rows={refusals}
            columns={REFUSAL_COLUMNS}
            rowKey={(r) => `${r.source}:${r.line}`}
            label="Refused lines"
            testId="connectors-refusal-table"
            rowTestId="connectors-refusal"
        />
    )
}

/** The refusals' columns: the source, the kind of line, how many lines, in how many runs, and the latest. */
const REFUSAL_COLUMNS: ReportColumn<ConnectorsRefusal>[] = [
    { key: 'source', kind: 'name', label: 'source', cell: (r) => <span className="font-mono">{r.source}</span> },
    { key: 'line', kind: 'word', label: 'line', cell: (r) => <span className="font-mono">{r.line}</span> },
    {
        key: 'lines',
        kind: 'figure',
        label: 'lines',
        cell: (r) => r.lines,
        tone: () => 'text-status-failed',
    },
    { key: 'runs', kind: 'figure', label: 'runs', hint: 'In how many runs', cell: (r) => r.runs, muted: true },
    { key: 'latest', kind: 'age', label: 'latest', cell: (r) => <Age at={r.last_at} variant="ago" /> },
]
