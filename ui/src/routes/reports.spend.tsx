import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { spendBreakdownQuery } from '@/api/queries'
import type { SpendBreakdownRange } from '@/api/queries'
import { SPEND_KINDS } from '@/api/types'
import type {
    SpendBreakdown,
    SpendDay,
    SpendKind,
    SpendMonth,
    SpendPullRequest,
    SpendSessions,
    SpendTicket,
} from '@/api/types'
import { Cost } from '@/components/cost'
import { None } from '@/components/none'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll, PanelSkeleton } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Clipped, Tip } from '@/components/tip'
import { TickRow } from '@/components/tick-row'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useMeasure } from '@/hooks/use-measure'
import { axisNames, axisStep, HEADROOM } from '@/lib/chart'
import type { AxisRoom } from '@/lib/chart'
import { useClock } from '@/lib/clock'
import type { Clock } from '@/lib/clock'
import { costText } from '@/lib/cost-total'
import { phaseMeaning } from '@/lib/meanings'
import {
    alertMarks,
    alertsText,
    BUDGET_WORD,
    budgetPartsText,
    budgetPercent,
    budgetState,
    budgetText,
    sessionsReadText,
    chartTop,
    dayHint,
    dayLabel,
    dayName,
    dearestDay,
    DEFAULT_WINDOW,
    doneText,
    GROUP_HINT,
    GROUP_LABEL,
    kindsOffered,
    modelRows,
    monthName,
    perRun,
    SERIES,
    seriesCost,
    shareText,
    SPEND_WINDOWS,
    spendLine,
    spendWindow,
    toolRows,
    unattributedShare,
    windowId,
    windowName,
} from '@/lib/spend'
import type { BudgetState, ModelRow, ToolRow } from '@/lib/spend'
import { tokenCount } from '@/lib/transcript'
import { cn } from '@/lib/utils'
import { NO_TICKET } from '@/lib/words'

interface SpendSearch {
    days?: number | undefined
    hours?: number | undefined
    model_kind?: SpendKind | undefined
    tool_kind?: SpendKind | undefined
}

// The search keys of the two kind filters, By model's and By tool's.
type KindKey = 'model_kind' | 'tool_kind'

// What the page shows on every visit, on its title's hover: its description is the window's state.
const HELP =
    'What agent runs cost each day, or each hour of the last 24, as the runtime reported it: the overseer, idle ' +
    "ticks' part of it apart, the workers, plans, chores, and reviews it started, and your tasks' runs; beside it, " +
    "the tickets the loop marked done, and what each ticket's and PR's own runs cost; what each kind spent on each " +
    "model; and which tools put the most into the runs' context. As canopy spend --days N prints it."

// What each share of the sessions panel counts, said when the operator hovers its name.
const SESSIONS_CANOPY_HINT =
    "The sessions this workspace's runs ran in, their subagents', and any that ran in its own .canopy directory"
const SESSIONS_OUTSIDE_HINT = "Every other session: yours, by hand, and other workspaces' canopy, by where it ran"

// What the window's spend per ticket done counts, on hover.
const PER_DONE_HINT =
    "canopy's whole spend in the window, the overseer's and chores' included, over the tickets marked done in it: " +
    'what getting them done cost, the runs of tickets still open included, the sessions outside canopy left out'

// What a tool's returned characters and its estimated tokens count, on hover.
const RETURNED_HINT =
    'The characters its calls returned, output or error: each later model call of the run reads them again'
const EST_TOKENS_HINT =
    "The characters over 4, an estimate: the runtime does not say which of a model call's tokens a tool returned"

// What a model's runs count, and why a kind's runs can have no model named, on hover.
const MODEL_RUNS_HINT = 'The runs it wrote a reply of: a run on two models counts under each'
const PER_RUN_HINT = 'What it spent over its runs: a run on two models counts its share of the cost under each'
const NO_MODEL_HINT =
    "Runs whose sessions named no model: not read yet, as a tick reads a few ended runs' sessions; no longer kept by " +
    'the runtime; failed to read; or making no model call. Their cost is what the runs reported'

// The column names of a table in a padded scrolling region. A sticky head sticks inside the region's padding, so the
// rows scrolling under it would show in a strip above it: the region's top padding is the head's cells' instead.
const PADDED_HEAD = 'sticky top-0 bg-surface [&_th]:pt-3'

// Each kind of run in words, as `canopy spend` counts the runs that reported no cost.
const KIND_LABEL = {
    overseer: 'overseer runs',
    workers: 'worker runs',
    plans: 'plan runs',
    chores: 'chore runs',
    reviews: 'review runs',
    tasks: 'task runs',
} as const

// Where the month stands against its budget, as its color and the budget bar's fill: a state's, never a spend
// series'.
const BUDGET_TEXT: Record<BudgetState, string> = {
    under: 'text-status-done',
    headed: 'text-status-blocked',
    over: 'text-status-failed',
}
const BUDGET_FILL: Record<BudgetState, string> = {
    under: 'bg-status-done',
    headed: 'bg-status-blocked',
    over: 'bg-status-failed',
}

// The order the totals name the series in: the overseer's whole, then idle ticks' part of it, as `canopy spend`'s
// columns read.
const TOTALS_ORDER = [
    'overseer',
    'idle',
    'workers',
    'plans',
    'chores',
    'reviews',
    'tasks',
    'dry_run',
    'outside',
] as const

// What the ticks' tables' last column counts, said when the operator hovers its name.
const NO_OVERSEER_HINT =
    'ticks that ran no overseer: the harness left it nothing to judge, or the tick halted before it; each cost nothing'

// The chart's axis names every day of up to a week, and every fifth day or hour past that, back from the latest.
const AXIS_ALL = 7
// The widest name the axis leaves room for at least, `Sep 30`, in characters, and the space it keeps from the next, in
// pixels. An hour on a 12-hour clock, `12:00 PM`, is wider, and gets its own.
const AXIS_NAME_CHARS = 6
const AXIS_GAP = 8

// Where the dearest day's total sits over its bar (`peakAlign`), and the class that puts it there.
type PeakAlign = 'start' | 'center' | 'end'
const PEAK_JUSTIFY: Record<PeakAlign, string> = {
    start: 'justify-start',
    center: 'justify-center',
    end: 'justify-end',
}

/**
 * What agent runs cost per day, by kind, and what the overseer's ticks bought, as `canopy spend` prints it, beside
 * what it got done: the tickets marked done, and what each ticket's and PR's own runs cost. The window is `?hours=24`,
 * by the hour, or `?days=`, a week or 30 days; the nav opens the week, and the rail's Spent counters their own window.
 * `?model_kind=` and `?tool_kind=` keep one kind's rows of By model and By tool, which otherwise sum every kind's.
 */
export const Route = createFileRoute('/reports/spend')({
    // Typed search params: a window the page does not offer is dropped, which reads as the week, and a kind it does
    // not count as every kind.
    validateSearch: (search: Record<string, unknown>): SpendSearch => {
        const picked = spendWindow(search)
        return {
            days: picked?.days,
            hours: picked?.hours,
            model_kind: SPEND_KINDS.find((k) => k === search['model_kind']),
            tool_kind: SPEND_KINDS.find((k) => k === search['tool_kind']),
        }
    },
    component: SpendPage,
})

function SpendPage() {
    const search = Route.useSearch()
    const shown = rangeOf(search)
    const navigate = Route.useNavigate()
    const query = useQuery(spendBreakdownQuery(shown))
    const clock = useClock()
    // What the empty panels say they looked over: `these 24 hours`, `these 7 days`.
    const span = windowName(shown)
    const { data } = query
    // The month against its budget, whatever the window; null with no budget set, and while nothing is read.
    const month = data?.month ?? null
    // A read that failed with nothing on screen says so once, in Totals, with Read again, rather than leave every panel
    // under it shimmering as if it were still coming.
    const failed = data === undefined && query.error !== null
    return (
        <>
            <PageHeader title="Spend" help={HELP}>
                {data === undefined ? (query.isPending ? 'reading the spend' : null) : spendLine(data)}
            </PageHeader>
            {!failed && (
                <Panel data-testid="spend-budget">
                    <PanelHeader label="This month">
                        <span className="readout text-xs text-muted-foreground">
                            {month === null ? '' : monthName(month)}
                        </span>
                    </PanelHeader>
                    {data === undefined ? <PanelSkeleton rows={1} className="min-h-16" /> : <Budget month={month} />}
                </Panel>
            )}
            <Panel data-testid="spend-totals">
                <PanelHeader label="Totals">
                    <ToggleGroup
                        type="single"
                        value={windowId(shown)}
                        aria-label="Window"
                        onValueChange={(value) => {
                            const picked = SPEND_WINDOWS.find((w) => windowId(w) === value)
                            // Pressing the window shown turns it off: keep it. The week, the default, needs no search;
                            // the kind filters stay as they are.
                            if (picked !== undefined) {
                                const week = picked === DEFAULT_WINDOW
                                void navigate({
                                    search: (prev) => ({
                                        ...prev,
                                        days: week ? undefined : picked.days,
                                        hours: week ? undefined : picked.hours,
                                    }),
                                })
                            }
                        }}
                    >
                        {SPEND_WINDOWS.map((w) => (
                            <ToggleGroupItem
                                key={windowId(w)}
                                value={windowId(w)}
                                data-testid={`spend-window-${windowId(w)}`}
                            >
                                {windowName(w)}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                </PanelHeader>
                {data === undefined ? <PanelLoading query={query} className="min-h-20" /> : <Totals found={data} />}
            </Panel>
            {!failed && (
                <>
                    <Panel data-testid="spend-by-day">
                        <PanelHeader label={shown.hours === undefined ? 'By day' : 'By hour'} />
                        {data === undefined ? (
                            <PanelSkeleton rows={6} className="min-h-72" />
                        ) : (
                            <ByDay days={data.per_day} span={span} unit={shown.hours === undefined ? 'day' : 'hour'} />
                        )}
                    </Panel>
                    <div className="grid gap-6 xl:grid-cols-2">
                        <Panel data-testid="spend-tickets">
                            <PanelHeader label="By ticket">
                                <span className="readout text-xs text-muted-foreground">
                                    {data?.tickets.length ?? ''}
                                </span>
                            </PanelHeader>
                            {data === undefined ? (
                                <PanelSkeleton rows={5} className="min-h-40" />
                            ) : (
                                <Tickets tickets={data.tickets} span={span} />
                            )}
                        </Panel>
                        <Panel data-testid="spend-pull-requests">
                            <PanelHeader label="By pull request">
                                <span className="readout text-xs text-muted-foreground">
                                    {data?.pull_requests.length ?? ''}
                                </span>
                            </PanelHeader>
                            {data === undefined ? (
                                <PanelSkeleton rows={5} className="min-h-40" />
                            ) : (
                                <PullRequests pullRequests={data.pull_requests} span={span} />
                            )}
                        </Panel>
                    </div>
                    <Panel data-testid="spend-models">
                        <PanelHeader label="By model">
                            <span className="flex flex-wrap items-center gap-x-3">
                                <KindFilter
                                    name="model_kind"
                                    kinds={kindsOffered(data?.models ?? [], search.model_kind)}
                                    chosen={search.model_kind}
                                />
                                {data !== undefined && (
                                    <Unattributed
                                        share={unattributedShare(modelRows(data.models, search.model_kind))}
                                    />
                                )}
                                <span className="readout text-xs text-muted-foreground" data-testid="spend-model-count">
                                    {data === undefined ? '' : modelCount(modelRows(data.models, search.model_kind))}
                                </span>
                            </span>
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton rows={4} className="min-h-32" />
                        ) : (
                            <Models
                                models={modelRows(data.models, search.model_kind)}
                                kind={search.model_kind}
                                span={span}
                            />
                        )}
                    </Panel>
                    <Panel data-testid="spend-tools">
                        <PanelHeader label="By tool">
                            <span className="flex flex-wrap items-center gap-x-3">
                                <KindFilter
                                    name="tool_kind"
                                    kinds={kindsOffered(data?.tools ?? [], search.tool_kind)}
                                    chosen={search.tool_kind}
                                />
                                <span className="readout text-xs text-muted-foreground" data-testid="spend-tool-count">
                                    {data === undefined ? '' : toolRows(data.tools, search.tool_kind).length}
                                </span>
                            </span>
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton rows={5} className="min-h-40" />
                        ) : (
                            <Tools tools={toolRows(data.tools, search.tool_kind)} kind={search.tool_kind} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="spend-sessions">
                        <PanelHeader label="Every session">
                            <span className="readout text-xs text-muted-foreground" data-testid="spend-sessions-read">
                                {data?.sessions === undefined || data.sessions === null
                                    ? ''
                                    : sessionsReadText(data.sessions, clock)}
                            </span>
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton rows={3} className="min-h-24" />
                        ) : (
                            <Sessions sessions={data.sessions ?? null} span={span} />
                        )}
                    </Panel>
                    <div className="grid gap-6 xl:grid-cols-2">
                        <Panel data-testid="spend-ticks">
                            <PanelHeader label="Ticks by what they bought" />
                            {data === undefined ? (
                                <PanelSkeleton rows={5} className="min-h-40" />
                            ) : (
                                <TickGroups found={data} span={span} />
                            )}
                        </Panel>
                        <Panel data-testid="spend-woken">
                            <PanelHeader label="Ticks by what woke them" />
                            {data === undefined ? (
                                <PanelSkeleton rows={4} className="min-h-40" />
                            ) : (
                                <Woken found={data} span={span} />
                            )}
                        </Panel>
                    </div>
                    <Panel data-testid="spend-idle-ticks">
                        <PanelHeader label="Idle ticks">
                            <span className="readout text-xs text-muted-foreground">
                                {data?.idle_ticks.length ?? ''}
                            </span>
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton className="min-h-24" />
                        ) : data.idle_ticks.length === 0 ? (
                            <Empty size="panel">no idle ticks in these {span}</Empty>
                        ) : (
                            <PanelScroll label="Idle ticks" className="max-h-96">
                                <ul className="divide-y" data-testid="spend-idle-tick-list">
                                    {data.idle_ticks.map((tick) => (
                                        <TickRow key={tick.id} tick={tick} />
                                    ))}
                                </ul>
                            </PanelScroll>
                        )}
                    </Panel>
                </>
            )}
        </>
    )
}

// The window the search names, the week when it names none.
function rangeOf(search: SpendSearch): SpendBreakdownRange {
    if (search.hours !== undefined) {
        return { hours: search.hours }
    }
    return search.days === undefined ? DEFAULT_WINDOW : { days: search.days }
}

/**
 * The local month so far against the monthly budget, whatever the window: a sentence with the numbers, what they are
 * made of, canopy's runs and the sessions outside canopy, and a bar of the budget spent, its fill the state's, beside a
 * mark at how much of the month has gone by. The bar is for the eye, so it is hidden from a screen reader, which reads
 * the sentences. With no budget set, where to set one.
 */
function Budget({ month }: { month: SpendMonth | null }) {
    const clock = useClock()
    if (month === null) {
        return (
            <p className="p-3 text-sm text-muted-foreground" data-testid="spend-budget-none">
                No monthly budget set. Set one under{' '}
                <Link to="/settings/limits" className="text-accent hover:underline">
                    Limits and trust
                </Link>{' '}
                to track the month against it here, and to have a sink that takes loop events hear once the month
                reaches it.
            </p>
        )
    }
    const state = budgetState(month)
    return (
        <div className="flex flex-col gap-2 p-3">
            <p className="text-sm text-foreground" data-testid="spend-budget-text">
                <span className={cn('font-medium', BUDGET_TEXT[state])}>{BUDGET_WORD[state]}</span>:{' '}
                <span className="readout">{budgetText(month)}</span>
            </p>
            <p className="text-xs text-muted-foreground" data-testid="spend-budget-parts">
                {budgetPartsText(month, clock)}
            </p>
            <div aria-hidden className="relative h-2 rounded-full bg-surface-raised" data-testid="spend-budget-meter">
                <div
                    className={cn('h-full rounded-full', BUDGET_FILL[state])}
                    style={{ width: `${Math.min(100, budgetPercent(month))}%` }}
                />
                {alertMarks(month).map((percent) => (
                    <div
                        key={percent}
                        className="absolute top-full mt-0.5 h-1.5 w-px bg-muted-foreground"
                        style={{ left: `${percent}%` }}
                        data-testid={`spend-budget-alert-${percent}`}
                    />
                ))}
                <div
                    className="absolute -inset-y-1 w-0.5 rounded-full bg-foreground"
                    style={{ left: `${Math.round(month.elapsed * 1000) / 10}%` }}
                />
            </div>
            <p className="mt-1 text-xs text-muted-foreground" data-testid="spend-budget-alerts">
                The mark is how much of the month has gone by: a bar past it is spending faster than the budget allows.
                {alertMarks(month).length > 0 && ' The ticks under it are your alerts short of the budget.'}{' '}
                {alertsText(month)}
            </p>
        </div>
    )
}

/**
 * The window's total, each kind's, and what it got done: the tickets marked done, and the whole spend over them. Then
 * idle ticks' share of the overseer's, when the overseer spent something, and the runs that reported no cost, when a
 * run ended.
 */
function Totals({ found }: { found: SpendBreakdown }) {
    const { totals } = found
    // Each series by the name the legend and the table give it, the overseer's whole before idle ticks' part of it.
    const cells = [
        { label: 'total', hint: undefined, usd: totals.total, testId: 'total' },
        ...TOTALS_ORDER.flatMap((key) => SERIES.filter((series) => series.key === key)).map((series) => ({
            label: series.label,
            hint: series.hint,
            usd: totals[series.key],
            testId: series.key.replace('_', '-'),
        })),
    ]
    const unpriced = found.unpriced
        .filter((u) => u.unpriced > 0)
        .map((u) => `${u.unpriced} of ${u.runs} ${KIND_LABEL[u.kind]}`)
        .join(', ')
    // In a window where nothing was spent, neither sentence has anything behind it: the share is of the live
    // overseer's spend, and the cost clause speaks for the runs that ended.
    const spent = found.idle_share !== null
    const ended = found.unpriced.some((u) => u.runs > 0)
    return (
        <div className="flex flex-col gap-3 p-3">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 @md:grid-cols-3 @4xl:grid-cols-10">
                {cells.map(({ label, hint, usd, testId }) => (
                    <div key={testId} className="flex flex-col gap-0.5">
                        <dt className="panel-label" title={hint}>
                            {label}
                        </dt>
                        <dd className="readout text-xl text-foreground" data-testid={`spend-total-${testId}`}>
                            <Cost usd={usd} />
                        </dd>
                    </div>
                ))}
            </dl>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-t pt-3 @md:grid-cols-3 @4xl:grid-cols-10">
                <div className="flex flex-col gap-0.5">
                    <dt
                        className="panel-label"
                        title="Merged, or closed in the tracker, which may close it as its PR merges"
                    >
                        tickets done
                    </dt>
                    <dd className="readout text-xl text-foreground" data-testid="spend-done">
                        {found.done}
                    </dd>
                </div>
                <div className="flex flex-col gap-0.5">
                    <dt className="panel-label" title={PER_DONE_HINT}>
                        per ticket done
                    </dt>
                    <dd className="readout text-xl text-foreground" data-testid="spend-per-done">
                        <Cost usd={found.per_done} />
                    </dd>
                </div>
            </dl>
            {(spent || ended) && (
                <p className="max-w-3xl text-xs text-muted-foreground" data-testid="spend-idle-share">
                    {spent && (
                        <>
                            Idle ticks were{' '}
                            <span className="readout text-foreground">{shareText(found.idle_share)}</span> of the live
                            overseer&apos;s spend.
                        </>
                    )}
                    {spent && ended && ' '}
                    {ended &&
                        (unpriced === '' ? 'Every run that ended reported a cost.' : `No cost reported: ${unpriced}.`)}
                </p>
            )}
        </div>
    )
}

/**
 * Each day, or hour, as a stacked bar, the series bottom up, with the legend under it, then the same numbers as a
 * table: the chart is for the eye, so a screen reader reads the table. A window where no run reported a cost says so,
 * in place of all three. A week's table shows whole; a longer one scrolls under its column names, so the panels below
 * stay in reach.
 */
function ByDay({ days, span, unit }: { days: SpendDay[]; span: string; unit: 'day' | 'hour' }) {
    const clock = useClock()
    if (chartTop(days) === 0) {
        return <Empty size="panel">no run reported a cost in these {span}</Empty>
    }
    return (
        <div className="flex flex-col gap-4 p-3">
            {/* Measured afresh for each window: another count of bars is another pitch. */}
            <Chart key={days.length} days={days} clock={clock} />
            <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" data-testid="spend-legend">
                {SERIES.map((series) => (
                    <li key={series.key} className="flex items-center gap-1.5" title={series.hint}>
                        <span aria-hidden className={cn('size-2.5 rounded-xs', series.fill)} />
                        {series.label}
                    </li>
                ))}
            </ul>
            <PanelScroll
                label={`Spend by ${unit}`}
                className="max-h-60 overflow-x-auto"
                data-testid="spend-table-scroll"
            >
                <table className="w-full border-collapse text-sm" data-testid="spend-table">
                    <thead className="sticky top-0 bg-surface">
                        <tr className="text-right">
                            <th className="panel-label pb-1.5 text-left font-normal">{unit}</th>
                            {SERIES.map((series) => (
                                <th
                                    key={series.key}
                                    className="panel-label pb-1.5 pl-3 font-normal"
                                    title={series.hint}
                                >
                                    {series.label}
                                </th>
                            ))}
                            <th className="panel-label pb-1.5 pl-3 font-normal">total</th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">done</th>
                        </tr>
                    </thead>
                    <tbody className="font-mono text-xs">
                        {days.toReversed().map((day) => (
                            <tr key={day.day} className="text-right" data-testid={`spend-day-${day.day}`}>
                                <th scope="row" className="readout py-0.5 text-left font-normal whitespace-nowrap">
                                    {dayName(day, clock)}
                                </th>
                                {SERIES.map((series) => (
                                    <td key={series.key} className="readout pl-3 text-muted-foreground">
                                        <Cost usd={day.costs[series.key]} />
                                    </td>
                                ))}
                                <td className="readout pl-3 text-foreground">
                                    <Cost usd={day.costs.total} />
                                </td>
                                <td className={cn('readout pl-3', day.done === 0 && 'text-muted-foreground')}>
                                    {day.done}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </PanelScroll>
        </div>
    )
}

/**
 * The bars over their axis, the row centered and each bar 3rem at most, so a sparse window draws narrow bars rather
 * than slabs. The axis names a day centered under its bar, whole, wider than the bar where it must be; where names
 * that often would touch, it names fewer days (`axisStep`).
 */
function Chart({ days, clock }: { days: SpendDay[]; clock: Clock }) {
    const names = days.map((day) => dayLabel(day, clock))
    const widest = Math.max(AXIS_NAME_CHARS, ...names.map((name) => name.length))
    // The same room is the same state: a new object each time would render again for nothing.
    const [measure, room] = useMeasure((chart: HTMLElement) => axisRoom(chart, widest), undefined, { same: sameRoom })
    const top = chartTop(days) * HEADROOM
    const dearest = dearestDay(days)
    const step = axisStep(days.length, AXIS_ALL, room)
    return (
        <div ref={measure} aria-hidden className="flex flex-col gap-1.5 px-3" data-testid="spend-chart">
            <div className="flex h-48 items-end justify-center gap-1">
                {days.map((day, i) => (
                    <Bar
                        key={day.day}
                        day={day}
                        top={top}
                        clock={clock}
                        peak={i === dearest ? peakAlign(i, days.length) : undefined}
                    />
                ))}
            </div>
            <div className="flex justify-center gap-1">
                {days.map((day, i) => (
                    <span key={day.day} className="relative h-4 max-w-12 min-w-0 flex-1">
                        {axisNames(i, days.length, step) && (
                            <span
                                className={cn(
                                    'readout absolute left-1/2 -translate-x-1/2',
                                    'text-2xs whitespace-nowrap text-muted-foreground',
                                )}
                                data-testid={`spend-axis-${day.day}`}
                            >
                                {names[i]}
                            </span>
                        )}
                    </span>
                ))}
            </div>
        </div>
    )
}

/**
 * What the drawn chart has room for: from one bar to the next, and the widest name a day can have, `widest`
 * characters, from the width of a name shown (the axis is monospace), with its gap. Undefined while there is nothing
 * to measure.
 */
function axisRoom(chart: HTMLElement, widest: number): AxisRoom | undefined {
    const [plot, axis] = chart.children
    const first = plot?.children[0]?.getBoundingClientRect()
    const second = plot?.children[1]?.getBoundingClientRect()
    const name = [...(axis?.children ?? [])].find((slot) => slot.firstElementChild !== null)?.firstElementChild
    const chars = name?.textContent.length ?? 0
    if (first === undefined || name === undefined || name === null || chars === 0) {
        return undefined
    }
    const width = name.getBoundingClientRect().width
    return {
        pitch: second === undefined ? Number.POSITIVE_INFINITY : Math.round(second.left - first.left),
        label: Math.ceil((width / chars) * widest) + AXIS_GAP,
    }
}

// Whether two measures of the axis leave it the same room.
function sameRoom(before: AxisRoom | undefined, after: AxisRoom | undefined): boolean {
    return before?.pitch === after?.pitch && before?.label === after?.label
}

/**
 * Where the dearest day's total sits over its bar: centered, but flush with the bar's outer edge on the first and the
 * last, since a total is wider than a narrow bar and the chart's padding is less than the half that would overhang.
 */
function peakAlign(i: number, count: number): PeakAlign {
    if (count > 1 && i === 0) {
        return 'start'
    }
    return count > 1 && i === count - 1 ? 'end' : 'center'
}

/**
 * One day's bar. Its segments stack bottom up, each its series' share of the day, at least 2px and 2px apart, the whole
 * as tall as the day's share of the chart's top; the dearest day's total sits over its bar. A day with no cost is a
 * stub on the baseline, so it reads as nothing spent rather than a column gone missing.
 */
function Bar({ day, top, clock, peak }: { day: SpendDay; top: number; clock: Clock; peak: PeakAlign | undefined }) {
    const segments = SERIES.map((series) => ({ series, usd: seriesCost(day.costs, series.key) })).filter(
        ({ usd }) => usd > 0,
    )
    const sum = segments.reduce((total, { usd }) => total + usd, 0)
    const height = ((day.costs.total ?? 0) / top) * 100
    return (
        <div
            className={cn(
                'relative flex h-full max-w-12 min-w-0 flex-1 flex-col justify-end',
                'rounded-t-xs hover:bg-surface-raised',
            )}
            title={dayHint(day, clock)}
            data-testid={`spend-bar-${day.day}`}
        >
            {sum === 0 ? (
                <span className="h-px w-full shrink-0 bg-border" data-testid="spend-stub" />
            ) : (
                <span
                    className="flex min-h-min w-full shrink-0 flex-col-reverse gap-0.5"
                    style={{ height: `${height}%` }}
                >
                    {segments.map(({ series, usd }) => (
                        <span
                            key={series.key}
                            className={cn('min-h-0.5 w-full last:rounded-t-xs', series.fill)}
                            // A share of 100, not of 1: flex factors that sum under 1 leave part of the bar unfilled.
                            style={{ flexGrow: (usd / sum) * 100, flexBasis: 0 }}
                            data-testid={`spend-segment-${series.key}`}
                        />
                    ))}
                </span>
            )}
            {peak !== undefined && (
                <span
                    className={cn(
                        'readout absolute inset-x-0 flex pb-0.5 text-2xs whitespace-nowrap',
                        PEAK_JUSTIFY[peak],
                    )}
                    style={{ bottom: `${height}%` }}
                    data-testid="spend-peak"
                >
                    <span>{costText(day.costs.total)}</span>
                </span>
            )}
        </div>
    )
}

/**
 * Each ticket with a run, or a review naming it, that started in the window, or marked done in it, the costliest
 * first: its key and title, its runs and reviews, what they cost, and when and how it was marked done. Not the
 * overseer's, whose ticks serve the whole workspace.
 */
function Tickets({ tickets, span }: { tickets: SpendTicket[]; span: string }) {
    if (tickets.length === 0) {
        return <Empty size="panel">no ticket had a run in these {span}</Empty>
    }
    return (
        <PanelScroll label="Spend by ticket" className="max-h-96 px-3 pb-3">
            <table className="w-full border-collapse text-sm" data-testid="spend-ticket-table">
                <thead className={PADDED_HEAD}>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">ticket</th>
                        <th className="panel-label pb-1.5 font-normal">runs</th>
                        <th className="panel-label pb-1.5 font-normal">spent</th>
                        <th className="panel-label pb-1.5 pl-3 text-left font-normal">done</th>
                    </tr>
                </thead>
                <tbody className="text-xs">
                    {tickets.map((ticket) => (
                        <tr key={ticket.key} className="text-right" data-testid={`spend-ticket-${ticket.key}`}>
                            <th scope="row" className="w-full max-w-0 py-0.5 text-left font-normal">
                                <span className="flex min-w-0 items-center gap-2">
                                    <TicketLink ticketKey={ticket.key} className="shrink-0" />
                                    <TicketTitle title={ticket.title} className="text-xs" />
                                </span>
                            </th>
                            <td className="readout pl-3" title={`${ticket.runs} runs, ${ticket.reviews} reviews`}>
                                {ticket.runs + ticket.reviews}
                            </td>
                            <td className="readout pl-3">
                                <Cost usd={ticket.cost_usd} />
                            </td>
                            <td className="readout pl-3 text-left whitespace-nowrap text-muted-foreground">
                                {doneText(ticket)}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}

/**
 * Each PR a run that started in the window pushed to, or a review of it did, the costliest first: the PR, its ticket,
 * its phase, its runs and reviews, and what they cost. A run that pushed to two PRs counts on each.
 */
function PullRequests({ pullRequests, span }: { pullRequests: SpendPullRequest[]; span: string }) {
    if (pullRequests.length === 0) {
        return <Empty size="panel">no run pushed to a PR, and none was reviewed, in these {span}</Empty>
    }
    return (
        <PanelScroll label="Spend by pull request" className="max-h-96 px-3 pb-3">
            <table className="w-full border-collapse text-sm" data-testid="spend-pull-request-table">
                <thead className={PADDED_HEAD}>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">pull request</th>
                        <th className="panel-label pb-1.5 pl-3 text-left font-normal">ticket</th>
                        <th className="panel-label pb-1.5 font-normal">runs</th>
                        <th className="panel-label pb-1.5 font-normal">spent</th>
                    </tr>
                </thead>
                <tbody className="text-xs">
                    {pullRequests.map((pr) => (
                        <tr key={pr.url} className="text-right" data-testid="spend-pull-request">
                            <th scope="row" className="w-full max-w-0 py-0.5 text-left font-normal">
                                <span className="flex min-w-0 items-center gap-2">
                                    <PullRequestLink url={pr.url} className="min-w-0" />
                                    {pr.phase !== null && (
                                        <Word
                                            word={pr.phase}
                                            meaning={phaseMeaning(pr.phase)}
                                            className="truncate text-muted-foreground"
                                        />
                                    )}
                                </span>
                            </th>
                            <td className="pl-3 text-left whitespace-nowrap">
                                {pr.ticket_key === null ? (
                                    <None reason={NO_TICKET} brief className="font-mono text-xs" />
                                ) : (
                                    <TicketLink ticketKey={pr.ticket_key} />
                                )}
                            </td>
                            <td className="readout pl-3" title={`${pr.runs} runs, ${pr.reviews} reviews`}>
                                {pr.runs + pr.reviews}
                            </td>
                            <td className="readout pl-3">
                                <Cost usd={pr.cost_usd} />
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}

/**
 * A panel's kind filter, in its header as the runs page's is: `all`, which sums every kind's rows, then each kind the
 * window has rows of. The choice is kept in the search under `name`, beside the window and the other filter.
 */
function KindFilter({ name, kinds, chosen }: { name: KindKey; kinds: SpendKind[]; chosen: SpendKind | undefined }) {
    return (
        <nav aria-label="Filter by kind" className="flex flex-wrap items-center gap-1" data-testid={`spend-${name}`}>
            <span className="mr-1 font-mono text-xs text-muted-foreground">kind</span>
            <KindLink name={name} kind={undefined} selected={chosen === undefined}>
                all
            </KindLink>
            {kinds.map((k) => (
                <KindLink key={k} name={name} kind={k} selected={chosen === k}>
                    {k}
                </KindLink>
            ))}
        </nav>
    )
}

/** A filter chip, the runs page's look: the search with `name` set to `kind`, or taken out for `all`. */
function KindLink({
    name,
    kind,
    selected,
    children,
}: {
    name: KindKey
    kind: SpendKind | undefined
    selected: boolean
    children: ReactNode
}) {
    return (
        <Link
            to="/reports/spend"
            search={(prev) => ({ ...prev, [name]: kind })}
            resetScroll={false}
            data-selected={selected}
            className={cn(
                'flex h-6 items-center gap-1.5 rounded-sm px-2 font-mono text-xs text-muted-foreground',
                'hover:bg-surface-raised hover:text-foreground',
                'data-[selected=true]:bg-accent/16 data-[selected=true]:text-foreground',
            )}
        >
            {children}
        </Link>
    )
}

/**
 * What the runs spent on each model, as their sessions say: every kind's summed, or one kind's, the most costly first,
 * and the runs no session named a model for last, muted. Each model's id, in mono as every page sets one, opens the
 * runs page's runs on it (`?model=`), and `per run` makes two models with different run counts comparable. Until a
 * tick has read any run's session, says so rather than list only those.
 */
function Models({ models, kind, span }: { models: ModelRow[]; kind: SpendKind | undefined; span: string }) {
    const runs = kind === undefined ? 'run' : KIND_LABEL[kind].replace(/s$/u, '')
    if (models.length === 0) {
        return (
            <Empty size="panel">
                no {runs} started in these {span}
            </Empty>
        )
    }
    if (models.every((m) => m.model === null)) {
        return (
            <Empty size="panel">
                no {runs}&apos;s model read in these {span} yet: a tick reads a few ended runs&apos; sessions
            </Empty>
        )
    }
    return (
        <PanelScroll label="Spend by model" className="max-h-96 px-3 pb-3">
            <table className="w-full border-collapse text-sm" data-testid="spend-model-table">
                <thead className={PADDED_HEAD}>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">model</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal" title={MODEL_RUNS_HINT}>
                            runs
                        </th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">replies</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">spent</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal whitespace-nowrap" title={PER_RUN_HINT}>
                            per run
                        </th>
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {models.map((m) => (
                        <tr key={m.model ?? ''} className="text-right" data-testid="spend-model">
                            <th
                                scope="row"
                                className="w-full max-w-0 py-0.5 text-left font-normal"
                                title={m.model === null ? NO_MODEL_HINT : undefined}
                            >
                                {m.model === null ? (
                                    <None reason="no session named one" className="block truncate font-sans" />
                                ) : (
                                    <Link
                                        to="/runs"
                                        search={{ model: m.model }}
                                        className="block text-accent underline-offset-4 hover:underline"
                                    >
                                        <Clipped text={m.model} className="block readout" />
                                    </Link>
                                )}
                            </th>
                            <td className="readout pl-3">{m.runs}</td>
                            <td className={cn('readout pl-3', m.model === null && 'text-muted-foreground')}>
                                {m.model === null ? '–' : m.replies}
                            </td>
                            <td className="readout pl-3">
                                <Cost usd={m.cost_usd} />
                            </td>
                            <td className="readout pl-3">
                                <Cost usd={perRun(m)} />
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}

/**
 * How much of what By model shows went on runs no session has named a model for yet (`unattributedShare`): the `none`
 * row's part, said in the header, since it is often the largest and sits last. Nothing when there is none.
 */
function Unattributed({ share }: { share: number | null }) {
    if (share === null) {
        return null
    }
    return (
        <Tip fact={NO_MODEL_HINT}>
            <span className="readout text-xs text-muted-foreground" data-testid="spend-model-unattributed">
                {shareText(share)} not yet attributed
            </span>
        </Tip>
    )
}

/** How many models the rows shown name, the runs no session named one for not among them. */
function modelCount(models: ModelRow[]): number | string {
    const named = models.filter((m) => m.model !== null).length
    return named === 0 ? '' : named
}

/**
 * What the tool calls returned, by tool, every kind's summed or one kind's, the most first: the calls, the errors, the
 * characters returned, and the tokens that is, estimated. After the fixed prefix, most of a run's context is tool
 * results, which each later model call reads again, so this is what fills it.
 */
function Tools({ tools, kind, span }: { tools: ToolRow[]; kind: SpendKind | undefined; span: string }) {
    if (tools.length === 0) {
        return (
            <Empty size="panel">
                no tool call recorded{kind === undefined ? '' : ` in ${KIND_LABEL[kind]}`} in these {span}
            </Empty>
        )
    }
    return (
        <PanelScroll label="Spend by tool" className="max-h-96 px-3 pb-3">
            <table className="w-full border-collapse text-sm" data-testid="spend-tool-table">
                <thead className={PADDED_HEAD}>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">tool</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">calls</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">errors</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal" title={RETURNED_HINT}>
                            returned
                        </th>
                        <th className="panel-label pb-1.5 pl-3 font-normal" title={EST_TOKENS_HINT}>
                            ~tokens
                        </th>
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {tools.map((tool) => (
                        <tr key={tool.tool} className="text-right" data-testid="spend-tool">
                            <th scope="row" className="w-full max-w-0 py-0.5 text-left font-normal">
                                {/* The row's name, as the ticket table's title reads: medium weight, cut to fit. */}
                                <Clipped text={tool.tool} className="block font-sans font-medium" />
                            </th>
                            <td className="readout pl-3" title={`in ${tool.runs} runs`}>
                                {tool.calls}
                            </td>
                            <td className={cn('readout pl-3', tool.errors === 0 && 'text-muted-foreground')}>
                                {tool.errors}
                            </td>
                            <td className="readout pl-3">{tokenCount(tool.result_chars)}</td>
                            <td className="readout pl-3">{tokenCount(tool.est_tokens)}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}

/** The ticks that ended in the window, a row per group, with idle ticks' share; a line saying so when none did. */
function TickGroups({ found, span }: { found: SpendBreakdown; span: string }) {
    if (found.ticks.every((g) => g.ticks === 0)) {
        return <Empty size="panel">no tick ended in these {span}</Empty>
    }
    return (
        <CountTable
            rows={found.ticks.map((g) => ({
                key: g.group,
                label: GROUP_LABEL[g.group],
                hint: GROUP_HINT[g.group],
                ticks: g.ticks,
                usd: g.cost_usd,
                without: g.without_overseer,
            }))}
            testId="spend-groups"
        />
    )
}

/** The loop's live ticks by what ended the wait before each, the most common first. */
function Woken({ found, span }: { found: SpendBreakdown; span: string }) {
    if (found.woken.length === 0) {
        return <Empty size="panel">no tick canopy loop ran in these {span}</Empty>
    }
    return (
        <CountTable
            rows={found.woken.map((w) => ({
                key: w.by,
                label: w.by,
                ticks: w.ticks,
                usd: w.cost_usd,
                without: w.without_overseer,
            }))}
            testId="spend-woken-table"
        />
    )
}

/**
 * Every session the runtime keeps that started in the window, canopy's apart from the rest, and where the rest ran,
 * the costliest directory first, as `canopy spend` lists them. Before `canopy loop` first reads them, why there are
 * none.
 */
function Sessions({ sessions, span }: { sessions: SpendSessions | null; span: string }) {
    if (typeof sessions?.read_at !== 'string') {
        return (
            <Empty size="panel">
                canopy loop has not read the runtime&apos;s sessions yet: it reads them, canopy&apos;s and yours,
                between ticks
            </Empty>
        )
    }
    if (sessions.canopy.sessions === 0 && sessions.outside.sessions === 0) {
        return <Empty size="panel">no session started in these {span}</Empty>
    }
    const shares = [
        { key: 'canopy', label: "canopy's runs", hint: SESSIONS_CANOPY_HINT, share: sessions.canopy },
        { key: 'outside', label: 'outside canopy', hint: SESSIONS_OUTSIDE_HINT, share: sessions.outside },
    ]
    return (
        <div className="flex flex-col gap-2 p-3">
            <table className="w-full border-collapse text-sm" data-testid="spend-sessions-table">
                <thead>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">sessions</th>
                        <th className="panel-label pb-1.5 font-normal">count</th>
                        <th className="panel-label pb-1.5 font-normal">spent</th>
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {shares.map(({ key, label, hint, share }) => (
                        <tr key={key} className="text-right" data-testid={`spend-sessions-${key}`}>
                            <th scope="row" className="py-0.5 text-left font-normal" title={hint}>
                                {label}
                            </th>
                            <td className="readout">{share.sessions}</td>
                            <td className="readout">
                                <Cost usd={share.cost_usd} />
                            </td>
                        </tr>
                    ))}
                    {sessions.directories.map((d) => (
                        <tr key={d.directory} className="text-right" data-testid="spend-sessions-directory">
                            <th scope="row" className="min-w-0 py-0.5 pl-4 text-left font-normal text-muted-foreground">
                                <Clipped text={d.directory} mono className="block" />
                            </th>
                            <td className="readout">{d.sessions}</td>
                            <td className="readout">
                                <Cost usd={d.cost_usd} />
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
            <p className="text-xs text-muted-foreground">
                A subagent&apos;s session counts with the session it ran for; another workspace&apos;s runs are outside.
            </p>
        </div>
    )
}

/**
 * Rows of a label, a tick count, what those ticks' overseers cost, and how many ran no overseer: the harness left it
 * nothing to judge, or the tick halted before it, so each cost nothing.
 */
function CountTable({
    rows,
    testId,
}: {
    rows: { key: string; label: string; hint?: string; ticks: number; usd: number | null; without: number }[]
    testId: string
}) {
    return (
        <div className="p-3">
            <table className="w-full border-collapse text-sm" data-testid={testId}>
                <thead>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">ticks</th>
                        <th className="panel-label pb-1.5 font-normal">count</th>
                        <th className="panel-label pb-1.5 font-normal">spent</th>
                        <th className="panel-label pb-1.5 font-normal" title={NO_OVERSEER_HINT}>
                            no overseer
                        </th>
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {rows.map((row) => (
                        <tr key={row.key} className="text-right" data-testid={`${testId}-${row.key}`}>
                            <th scope="row" className="py-0.5 text-left font-normal" title={row.hint}>
                                {row.label}
                            </th>
                            <td className="readout">{row.ticks}</td>
                            <td className="readout">
                                <Cost usd={row.usd} />
                            </td>
                            <td className="readout">{row.without}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
