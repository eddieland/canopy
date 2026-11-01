import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { spendBreakdownQuery } from '@/api/queries'
import type { SpendBreakdownRange } from '@/api/queries'
import { SPEND_KINDS } from '@/api/types'
import type {
    SpendBreakdown,
    SpendCosts,
    SpendDay,
    SpendFirstCallWeek,
    SpendKind,
    SpendMonth,
    SpendPullRequest,
    SpendSessions,
    SpendShare,
    SpendTicket,
} from '@/api/types'
import { CellBar } from '@/components/cell-bar'
import { ChartTable } from '@/components/chart-table'
import { Cost } from '@/components/cost'
import { DayChart, DayChartLegend } from '@/components/day-chart'
import { FirstCallChart } from '@/components/first-call-chart'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll, PanelSkeleton } from '@/components/panel'
import { PullRequestTable } from '@/components/pull-request-table'
import type { PullRequestColumn } from '@/components/pull-request-table'
import { ReadoutTiles } from '@/components/readout-tiles'
import type { ReadoutTile } from '@/components/readout-tiles'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Clipped, Hinted, Tip, Tipped } from '@/components/tip'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { UnnamedModel } from '@/components/unnamed-model'
import { WindowToggle } from '@/components/window-toggle'
import { barPercent } from '@/lib/chart'
import { useClock } from '@/lib/clock'
import { counted } from '@/lib/descriptions'
import { firstKind, KIND_SERIES, seriesOf, seriesWeeks } from '@/lib/first-calls'
import { unnamedHint, UNREAD, UNREAD_RUNS_HINT } from '@/lib/models'
import { readoutDelta, usdChange, wholeChange } from '@/lib/readout-delta'
import { windowBefore, windowName } from '@/lib/report-window'
import {
    alertMarks,
    alertsText,
    BUDGET_WORD,
    budgetPartsText,
    budgetPercent,
    budgetState,
    budgetDayText,
    budgetSpentText,
    foldedText,
    paceText,
    spendWeeks,
    weekBars,
    weekName,
    weeksOffered,
    sessionsReadText,
    chartTop,
    dayName,
    DEFAULT_WINDOW,
    doneText,
    GROUP_HINT,
    GROUP_LABEL,
    KIND_LABEL,
    kindsOffered,
    listedModels,
    modelKind,
    modelKey,
    modelRows,
    monthName,
    perRun,
    RUNS_KIND,
    SERIES,
    shareText,
    SPEND_WINDOWS,
    spendLine,
    spendBars,
    spendWindow,
    unpricedText,
    toolRows,
    unreadShare,
    workspacePerRun,
} from '@/lib/spend'
import type { BudgetState, ModelRow, ToolRow } from '@/lib/spend'
import { tokenCount } from '@/lib/transcript'
import { cn } from '@/lib/utils'

interface SpendSearch {
    days?: number | undefined
    hours?: number | undefined
    // `all` keeps every kind while a ticket is set, whose own default is its workers.
    model_kind?: SpendKind | 'all' | undefined
    tool_kind?: SpendKind | undefined
    first_kind?: SpendKind | undefined
    first_series?: string | undefined
    ticket?: string | undefined
    // By day's pitch over 30 days: a bar per week rather than per day.
    pitch?: 'week' | undefined
}

// The search keys of the kind filters: By model's, By tool's, and First calls by week's.
type KindKey = 'model_kind' | 'tool_kind' | 'first_kind'

// What a bar of By day stands for: an hour in a window of hours, else a day, or a week when picked over 30 days.
type Pitch = 'hour' | 'day' | 'week'

// A row of By day's table: its test id's end, its name, and its figures.
interface PitchRow {
    key: string
    name: string
    costs: SpendCosts
    done: number
}

// What the page shows on every visit, on its title's hover: its description is the window's state.
const HELP =
    'What agent runs cost each day, or each hour of the last 24, as the runtime reported it: the overseer, idle ' +
    "ticks' part of it apart, the workers, plans, chores, and reviews it started, and your tasks' runs; beside it, " +
    "the tickets the loop marked done, and what each ticket's and PR's own runs cost; what each kind spent on each " +
    "model; which tools put the most into the runs' context; and how much of each kind's first model call the cache " +
    "served, week by week. As canopy spend --days N prints it. This month's bar fills with the budget spent; " +
    'the mark across it is how far through the month you are, so a bar past its mark is spending faster than the ' +
    'budget allows, and the ticks over it are your alerts short of the budget, each heard once by a sink that takes ' +
    'loop events.'

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
const WORKSPACE_HINT =
    "What the workspace's runs of the kind spent on the model, over its runs: this ticket's among them, every other " +
    "ticket's too"
const UNLISTED_HINT = 'The runs page lists no overseer tick by model: Ticks, under Workspace, lists them by tick'

// The Totals panel's tiles: two to a row on a phone, three on a tablet, every one in a row on a wide pane.
const TOTALS_GRID = 'grid grid-cols-2 gap-x-6 gap-y-3 @md:grid-cols-3 @4xl:grid-cols-10'

// The column names of a table in a padded scrolling region. A sticky head sticks inside the region's padding, so the
// rows scrolling under it would show in a strip above it: the region's top padding is the head's cells' instead.
const PADDED_HEAD = 'sticky top-0 bg-surface [&_th]:pt-3'

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

// What the Ticks panel's two tables group the ticks by, said on the hover of each one's first column's name.
const BOUGHT_HINT = 'What the tick bought: whether the loop found it idle, ran it by hand, or it ended other than ok'
const WOKEN_HINT =
    "What ended the loop's wait before the tick: its start, its timer, a run ending, your message, and so on"

// What the ticks' tables' last column counts, said when the operator hovers its name.
const NO_OVERSEER_HINT =
    'ticks that ran no overseer: the harness left it nothing to judge, or the tick halted before it; each cost nothing'

/**
 * What agent runs cost per day, by kind, and what the overseer's ticks bought, as `canopy spend` prints it, beside
 * what it got done: the tickets marked done, and what each ticket's and PR's own runs cost. The window is `?hours=24`,
 * by the hour, or `?days=`, a week or 30 days; the nav opens the week, and the rail's Spent counters their own window.
 * `?model_kind=` and `?tool_kind=` keep one kind's rows of By model and By tool, which otherwise sum every kind's.
 * `?ticket=` narrows By model to that ticket's runs, each beside the workspace's per run, and opens it on its workers'
 * (`modelKind`), which `?model_kind=all` widens again; every other panel is the workspace's still.
 * `?first_kind=` picks the kind First calls by week draws, the first with a week otherwise, and `?first_series=` one
 * of its chores or models, `chore:deps` or `model:` and the model's id, in place of all its runs.
 */
export const Route = createFileRoute('/reports/spend')({
    // Typed search params: a window the page does not offer is dropped, which reads as the week, and a kind it does
    // not count as every kind.
    validateSearch: (search: Record<string, unknown>): SpendSearch => {
        const picked = spendWindow(search)
        return {
            days: picked?.days,
            hours: picked?.hours,
            model_kind: search['model_kind'] === 'all' ? 'all' : SPEND_KINDS.find((k) => k === search['model_kind']),
            tool_kind: SPEND_KINDS.find((k) => k === search['tool_kind']),
            first_kind: SPEND_KINDS.find((k) => k === search['first_kind']),
            // Any series is kept: one the window's weeks do not have reads as the kind's own.
            first_series: typeof search['first_series'] === 'string' ? search['first_series'] : undefined,
            ticket: typeof search['ticket'] === 'string' && search['ticket'] !== '' ? search['ticket'] : undefined,
            pitch: search['pitch'] === 'week' ? 'week' : undefined,
        }
    },
    component: SpendPage,
})

function SpendPage() {
    const search = Route.useSearch()
    const shown = rangeOf(search)
    const navigate = Route.useNavigate()
    const query = useQuery(spendBreakdownQuery(shown, search.ticket))
    // By model's kind: the one chosen, or a ticket's workers'.
    const modelsOf = modelKind(search.model_kind, search.ticket)
    const clock = useClock()
    // What the empty panels say they looked over: `these 24 hours`, `these 7 days`.
    const span = windowName(shown)
    // By day's pitch: the hour in a window of hours, the week when picked over 30 days, else the day.
    const pitch = pitchOf(shown, search.pitch)
    const { data } = query
    // The month against its budget, whatever the window; null with no budget set, and while nothing is read.
    const month = data?.month ?? null
    // A read that failed with nothing on screen says so once, in Totals, with Read again, rather than leave every panel
    // under it shimmering as if it were still coming.
    const failed = data === undefined && query.error !== null
    return (
        <>
            <PageHeader
                title="Spend"
                help={HELP}
                controls={
                    <WindowToggle
                        windows={SPEND_WINDOWS}
                        shown={shown}
                        testId="spend"
                        onPick={(picked) => {
                            // The week, the default, needs no search; the kind filters stay as they are.
                            const week = picked === DEFAULT_WINDOW
                            void navigate({
                                search: (prev) => ({
                                    ...prev,
                                    days: week ? undefined : picked.days,
                                    hours: week ? undefined : picked.hours,
                                }),
                            })
                        }}
                    />
                }
            >
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
                <PanelHeader label="Totals" />
                {data === undefined ? <PanelLoading query={query} className="min-h-20" /> : <Totals found={data} />}
            </Panel>
            {!failed && (
                <>
                    <Panel data-testid="spend-by-day">
                        <PanelHeader label={`By ${pitch}`}>
                            {weeksOffered(shown) && (
                                <PitchToggle
                                    pitch={pitch}
                                    onPick={(picked) => {
                                        void navigate({
                                            search: (prev) => ({
                                                ...prev,
                                                pitch: picked === 'week' ? 'week' : undefined,
                                            }),
                                            resetScroll: false,
                                        })
                                    }}
                                />
                            )}
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton rows={6} className="min-h-72" />
                        ) : (
                            <ByDay days={data.per_day} span={span} pitch={pitch} />
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
                                {search.ticket !== undefined && <TicketScope ticket={search.ticket} />}
                                <KindFilter
                                    name="model_kind"
                                    kinds={kindsOffered(data?.models ?? [], modelsOf)}
                                    chosen={modelsOf}
                                />
                                {data !== undefined && <Unread share={unreadShare(modelRows(data.models, modelsOf))} />}
                                <span className="readout text-xs text-muted-foreground" data-testid="spend-model-count">
                                    {data === undefined ? '' : modelCount(modelRows(data.models, modelsOf))}
                                </span>
                            </span>
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton rows={4} className="min-h-32" />
                        ) : (
                            <Models
                                models={modelRows(data.models, modelsOf)}
                                kind={modelsOf}
                                listed={listedModels(data.models)}
                                span={span}
                                ticket={search.ticket}
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
                    <Panel data-testid="spend-first-calls">
                        <PanelHeader label="First calls by week">
                            <KindFilter
                                name="first_kind"
                                kinds={kindsOffered(data?.first_call_weeks ?? [], search.first_kind)}
                                chosen={firstKind(data?.first_call_weeks ?? [], search.first_kind)}
                                every={false}
                            />
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton rows={6} className="min-h-72" />
                        ) : (
                            <FirstCalls
                                weeks={data.first_call_weeks}
                                kind={firstKind(data.first_call_weeks, search.first_kind)}
                                series={search.first_series ?? KIND_SERIES}
                                span={span}
                            />
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
                    <Panel data-testid="spend-ticks">
                        <PanelHeader label="Ticks">
                            {data !== undefined && <IdleShare share={data.idle_share} />}
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton rows={5} className="min-h-40" />
                        ) : (
                            <Ticks found={data} span={span} />
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

// By day's pitch in the window shown: a week picked in a window that offers none reads as the day.
function pitchOf(shown: SpendBreakdownRange, picked: 'week' | undefined): Pitch {
    if (shown.hours !== undefined) {
        return 'hour'
    }
    return picked === 'week' && weeksOffered(shown) ? 'week' : 'day'
}

/**
 * By day's pitch, beside its label over 30 days: `day` or `week`, a segmented control as the window is, so a month's
 * trend can read as four or five bars rather than thirty.
 */
function PitchToggle({ pitch, onPick }: { pitch: Pitch; onPick: (picked: Pitch) => void }) {
    return (
        <ToggleGroup
            type="single"
            value={pitch}
            aria-label="Pitch"
            onValueChange={(value) => {
                // Pressing the pitch shown turns it off, which reads as no value: keep it.
                if (value === 'day' || value === 'week') {
                    onPick(value)
                }
            }}
        >
            <ToggleGroupItem value="day" data-testid="spend-pitch-day">
                by day
            </ToggleGroupItem>
            <ToggleGroupItem value="week" data-testid="spend-pitch-week">
                by week
            </ToggleGroupItem>
        </ToggleGroup>
    )
}

/**
 * The local month so far against the monthly budget, whatever the window: what it spent, what that is made of,
 * canopy's runs and the sessions outside canopy, a bar of the budget spent, its fill the state's, and a line on where
 * its pace takes it. The bar labels itself: the mark across it, how much of the month has gone by, is the day under it
 * (`day 8 of 31`), and each alert short of the budget a tick over it with its percent; each label's offset follows its
 * place on the bar, so one at an end sits flush with it. The bar is for the eye, so it is hidden from a screen reader,
 * which reads the day and the alerts in a sentence of its own. What the bar means is the title's help. With no budget
 * set, where to set one.
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
    const elapsed = Math.round(month.elapsed * 1000) / 10
    const day = budgetDayText(month)
    const pace = paceText(month)
    return (
        <div className="flex flex-col gap-2 p-3">
            <p className="text-sm text-foreground" data-testid="spend-budget-text">
                <span className={cn('font-medium', BUDGET_TEXT[state])}>{BUDGET_WORD[state]}</span>:{' '}
                <span className="readout">{budgetSpentText(month)}</span>
            </p>
            <p className="text-xs text-muted-foreground" data-testid="spend-budget-parts">
                {budgetPartsText(month, clock)}
            </p>
            <div aria-hidden className="relative pt-5 pb-5" data-testid="spend-budget-meter">
                {alertMarks(month).map((percent) => (
                    <BarLabel key={percent} at={percent} className="top-0" testId={`spend-budget-alert-${percent}`}>
                        {percent}%
                    </BarLabel>
                ))}
                <div className="relative h-2 rounded-full bg-surface-raised">
                    <div
                        className={cn('h-full rounded-full', BUDGET_FILL[state])}
                        style={{ width: `${Math.min(100, budgetPercent(month))}%` }}
                    />
                    {alertMarks(month).map((percent) => (
                        <div
                            key={percent}
                            className="absolute bottom-full mb-0.5 h-1.5 w-px bg-muted-foreground"
                            style={{ left: `${percent}%` }}
                        />
                    ))}
                    <div
                        className="absolute -inset-y-1 w-0.5 rounded-full bg-foreground"
                        style={{ left: `${elapsed}%` }}
                    />
                </div>
                <BarLabel at={elapsed} className="bottom-0" testId="spend-budget-day">
                    {day}
                </BarLabel>
            </div>
            <p className="sr-only" data-testid="spend-budget-alerts">
                {`It is ${day} of the month. ${alertsText(month)}`}
            </p>
            {pace !== null && (
                <p className="text-xs text-muted-foreground" data-testid="spend-budget-pace">
                    {pace}
                </p>
            )}
        </div>
    )
}

/**
 * A label on the budget's bar at `at` percent along it, over or under it by `className`: its offset is its own width
 * times the same percent, so one at either end sits flush with the bar's, and one in the middle centers on its mark.
 */
function BarLabel({
    at,
    className,
    testId,
    children,
}: {
    at: number
    className: string
    testId: string
    children: ReactNode
}) {
    return (
        <span
            className={cn('readout absolute text-2xs leading-none whitespace-nowrap text-muted-foreground', className)}
            style={{ left: `${at}%`, transform: `translateX(-${at}%)` }}
            data-testid={testId}
        >
            {children}
        </span>
    )
}

/**
 * The window's total, each kind's, and what it got done: the tickets marked done, and the whole spend over them, each
 * against the window before's, where more tickets done is better and spend is never colored. A kind that reported no
 * cost is no tile, a dash in a figure's room, but a muted line under them (`No dry runs.`), so the tiles hold what was
 * spent; when every kind is so, the total's dash says it alone. The grid's cells are too narrow to name the window
 * before under each figure, so a line under them names it once. Then the runs that reported no cost, when a run ended.
 */
function Totals({ found }: { found: SpendBreakdown }) {
    const { totals, previous } = found
    // Each series by the name the legend and the table give it, the overseer's whole before idle ticks' part of it.
    const ordered = TOTALS_ORDER.flatMap((key) => SERIES.filter((series) => series.key === key))
    const spent = ordered.filter((series) => totals[series.key] !== null)
    const unspent = spent.length === 0 ? [] : ordered.filter((series) => !spent.includes(series))
    const folded = foldedText(unspent, typeof found.sessions?.read_at === 'string')
    const cells: ReadoutTile[] = [
        {
            key: 'total',
            label: 'total',
            value: <Cost usd={totals.total} />,
            delta: readoutDelta(totals.total, previous.totals.total, usdChange),
        },
        ...spent.map((series) => ({
            key: series.key.replace('_', '-'),
            label: series.label,
            hint: series.hint,
            value: <Cost usd={totals[series.key]} />,
            delta: readoutDelta(totals[series.key], previous.totals[series.key], usdChange),
        })),
    ]
    const done: ReadoutTile[] = [
        {
            key: 'done',
            label: 'tickets done',
            hint: 'Merged, or closed in the tracker, which may close it as its PR merges',
            value: found.done,
            delta: readoutDelta(found.done, previous.done, wholeChange, 'up'),
        },
        {
            key: 'per-done',
            label: 'per ticket done',
            hint: PER_DONE_HINT,
            value: <Cost usd={found.per_done} />,
            delta: readoutDelta(found.per_done, previous.per_done, usdChange),
        },
    ]
    const compared = [...cells, ...done].some((tile) => tile.delta !== null && tile.delta !== undefined)
    // In a window where no run ended, the cost clause has nothing to speak for.
    const ended = found.unpriced.some((u) => u.runs > 0)
    return (
        <div className="flex flex-col gap-3 p-3">
            <ReadoutTiles tiles={cells} testId="spend-total" className={TOTALS_GRID} />
            {folded !== '' && (
                <p className="-mt-1 text-xs text-muted-foreground" data-testid="spend-total-folded">
                    {folded}
                </p>
            )}
            <ReadoutTiles tiles={done} testId="spend" className={cn(TOTALS_GRID, 'border-t pt-3')} />
            {compared && (
                <p className="text-xs text-muted-foreground" data-testid="spend-against">
                    Each change under a figure is on {windowBefore(found)}.
                </p>
            )}
            {ended && (
                <p className="max-w-3xl text-xs text-muted-foreground" data-testid="spend-unpriced">
                    {unpricedText(found.unpriced)}
                </p>
            )}
        </div>
    )
}

/**
 * Each day, hour, or week, by `pitch`, as a stacked bar, the series bottom up, with the legend under it, then the same
 * numbers as a table: the chart is for the eye, so a screen reader reads the table. A window where no run reported a
 * cost says so, in place of all three. A week's table shows whole; a longer one scrolls under its column names, so the
 * panels below stay in reach.
 */
function ByDay({ days, span, pitch }: { days: SpendDay[]; span: string; pitch: Pitch }) {
    const clock = useClock()
    if (chartTop(days) === 0) {
        return <Empty size="panel">no run reported a cost in these {span}</Empty>
    }
    // Only days sum into weeks: an hour's name is no date.
    const weeks = pitch === 'week' ? spendWeeks(days) : []
    const weekRows = weeks.map((week) => ({ key: `week-${week.week}`, name: weekName(week), ...week }))
    const dayRows = days.map((day) => ({ key: `day-${day.day}`, name: dayName(day, clock), ...day }))
    const rows: PitchRow[] = pitch === 'week' ? weekRows : dayRows
    const bars = pitch === 'week' ? weekBars(weeks) : spendBars(days, clock)
    return (
        <div className="flex flex-col gap-4 p-3">
            {/* Measured afresh for each window and pitch: another count of bars is another pitch. */}
            <DayChart key={bars.length} bars={bars} testId="spend" />
            <DayChartLegend series={SERIES} testId="spend" />
            <ChartTable
                what={counted(rows.length, pitch)}
                label={`Spend by ${pitch}`}
                className="max-h-60 overflow-x-auto"
                testId="spend-table-scroll"
            >
                <table className="w-full border-collapse text-sm" data-testid="spend-table">
                    <thead className="sticky top-0 bg-surface">
                        <tr className="text-right">
                            <th className="panel-label pb-1.5 text-left font-normal">{pitch}</th>
                            {SERIES.map((series) => (
                                <th key={series.key} className="panel-label pb-1.5 pl-3 font-normal">
                                    {series.label}
                                </th>
                            ))}
                            <th className="panel-label pb-1.5 pl-3 font-normal">total</th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">done</th>
                        </tr>
                    </thead>
                    <tbody className="font-mono text-xs">
                        {rows.toReversed().map((row) => (
                            <tr key={row.key} className="text-right" data-testid={`spend-${row.key}`}>
                                <th scope="row" className="readout py-0.5 text-left font-normal whitespace-nowrap">
                                    {row.name}
                                </th>
                                {SERIES.map((series) => (
                                    <td key={series.key} className="readout pl-3 text-muted-foreground">
                                        <Cost usd={row.costs[series.key] ?? null} />
                                    </td>
                                ))}
                                <td className="readout pl-3 text-foreground">
                                    <Cost usd={row.costs.total ?? null} />
                                </td>
                                <td className={cn('readout pl-3', row.done === 0 && 'text-muted-foreground')}>
                                    {row.done}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </ChartTable>
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
                            <td className="readout pl-3">
                                <Tipped fact={`${ticket.runs} runs, ${ticket.reviews} reviews`}>
                                    {ticket.runs + ticket.reviews}
                                </Tipped>
                            </td>
                            <td className="pl-3">
                                <CellBar
                                    percent={barPercent(
                                        ticket.cost_usd,
                                        tickets.map((t) => t.cost_usd),
                                    )}
                                    valueClassName="w-16 text-right"
                                >
                                    <Cost usd={ticket.cost_usd} />
                                </CellBar>
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
        <PullRequestTable
            rows={pullRequests}
            columns={pullRequestColumns(pullRequests)}
            label="Spend by pull request"
            testId="spend"
        />
    )
}

// What the spend page counts of each PR: its runs and reviews, and what they cost, a bar of its share of the dearest's.
function pullRequestColumns(rows: readonly SpendPullRequest[]): PullRequestColumn<SpendPullRequest>[] {
    const spent = rows.map((pr) => pr.cost_usd)
    return [
        {
            key: 'runs',
            label: 'runs',
            cell: (pr) => pr.runs + pr.reviews,
            title: (pr) => `${pr.runs} runs, ${pr.reviews} reviews`,
        },
        {
            key: 'spent',
            label: 'spent',
            cell: (pr) => (
                <CellBar percent={barPercent(pr.cost_usd, spent)} valueClassName="w-16 text-right">
                    <Cost usd={pr.cost_usd} />
                </CellBar>
            ),
        },
    ]
}

/**
 * A panel's kind filter, in its header as the runs page's is: `all`, which sums every kind's rows, unless `every` is
 * false for a panel whose kinds do not sum, then each kind the window has rows of. The choice is kept in the search
 * under `name`, beside the window and the other filters.
 */
function KindFilter({
    name,
    kinds,
    chosen,
    every = true,
}: {
    name: KindKey
    kinds: SpendKind[]
    chosen: SpendKind | undefined
    every?: boolean
}) {
    return (
        <nav aria-label="Filter by kind" className="flex flex-wrap items-center gap-1" data-testid={`spend-${name}`}>
            <span className="mr-1 font-mono text-xs text-muted-foreground">kind</span>
            {every && (
                <KindLink name={name} kind={undefined} selected={chosen === undefined}>
                    all
                </KindLink>
            )}
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
        // Another kind of first calls has other chores and models: its series starts as all its runs.
        <FilterLink
            search={(prev) => ({
                ...prev,
                [name]: kind ?? (name === 'model_kind' && prev.ticket !== undefined ? 'all' : undefined),
                ...(name === 'first_kind' && { first_series: undefined }),
            })}
            selected={selected}
        >
            {children}
        </FilterLink>
    )
}

/**
 * The ticket By model is narrowed to, in its header: its key, opening its page, then a chip that widens the table to
 * every ticket's runs again, the kind chosen kept.
 */
function TicketScope({ ticket }: { ticket: string }) {
    return (
        <span className="flex items-center gap-1" data-testid="spend-model-ticket">
            <span className="mr-1 font-mono text-xs text-muted-foreground">ticket</span>
            <TicketLink ticketKey={ticket} />
            <FilterLink
                search={(prev) => ({
                    ...prev,
                    ticket: undefined,
                    model_kind: prev.model_kind === 'all' ? undefined : prev.model_kind,
                })}
                selected={false}
            >
                every ticket
            </FilterLink>
        </span>
    )
}

/** A filter chip, the runs page's look: the page with `search` as its search, marked when it is the one shown. */
function FilterLink({
    search,
    selected,
    className,
    children,
}: {
    search: (prev: SpendSearch) => SpendSearch
    selected: boolean
    className?: string
    children: ReactNode
}) {
    return (
        <Link
            to="/reports/spend"
            search={search}
            resetScroll={false}
            data-selected={selected}
            className={cn(
                'flex h-6 min-w-0 items-center gap-1.5 rounded-sm px-2 font-mono text-xs text-muted-foreground',
                'hover:bg-surface-raised hover:text-foreground',
                'data-[selected=true]:bg-accent/16 data-[selected=true]:text-foreground',
                className,
            )}
        >
            {children}
        </Link>
    )
}

/**
 * The first calls panel's body: the kind's series to pick from, all its runs, each chore's, and each model's, then the
 * picked one's weeks drawn (`FirstCallChart`) in the kind's fill, and a line on what to read in them. A window with no
 * first call recorded, of any kind or of the kind picked, says so.
 */
function FirstCalls({
    weeks,
    kind,
    series,
    span,
}: {
    weeks: SpendFirstCallWeek[]
    kind: SpendKind | undefined
    series: string
    span: string
}) {
    if (kind === undefined) {
        return <Empty size="panel">no run reported its first model call in these {span}</Empty>
    }
    const offered = seriesOf(weeks, kind)
    const shown = offered.some((s) => s.id === series) ? series : KIND_SERIES
    const drawn = seriesWeeks(weeks, kind, shown)
    if (drawn.length === 0) {
        return (
            <Empty size="panel">
                no {KIND_LABEL[kind].replace(/s$/u, '')} reported its first model call in these {span}
            </Empty>
        )
    }
    const fill = SERIES.find((s) => s.key === kind)?.fill ?? 'bg-spend-workers'
    return (
        <div className="flex flex-col">
            {offered.length > 1 && (
                <nav
                    aria-label="Filter by chore or model"
                    className="flex flex-wrap items-center gap-1 px-3 pt-3"
                    data-testid="spend-first-series"
                >
                    <span className="mr-1 font-mono text-xs text-muted-foreground">runs</span>
                    {offered.map((s) => (
                        <FilterLink
                            key={s.id}
                            search={(prev) => ({ ...prev, first_series: s.id === KIND_SERIES ? undefined : s.id })}
                            selected={s.id === shown}
                            className="max-w-full"
                        >
                            <Clipped text={s.label} className="block" />
                        </FilterLink>
                    ))}
                </nav>
            )}
            <FirstCallChart weeks={drawn} fill={fill} />
            <p className="max-w-3xl px-3 pb-3 text-xs text-muted-foreground">
                Each bar is how much of the week&apos;s first model calls the cache served: the prefix every run starts
                with. A fall is a prefix the cache no longer holds; a rule marks a week whose runs used a runtime
                version or definitions snapshot the week before&apos;s did not.
            </p>
        </div>
    )
}

/**
 * What the runs spent on each model, as their sessions say: every kind's summed, or one kind's, the most costly first,
 * and the runs no session named a model for last, muted: `unread`, then `none` (`UnnamedModel`). Each model's id, in
 * mono as every page sets one, opens the runs page's runs on it (`?model=`), of the kind shown (`?kind=`,
 * `RUNS_KIND`), and `per run` makes two models with different run counts comparable. A model the runs page cannot list
 * a run of, as only the overseer's ticks used it (`listed`), is plain, why on hover. Until a tick has read any run's
 * session, says so rather than list only those unread.
 */
function Models({
    models,
    kind,
    listed,
    span,
    ticket,
}: {
    models: ModelRow[]
    kind: SpendKind | undefined
    listed: ReadonlySet<string>
    span: string
    ticket: string | undefined
}) {
    // The runs page's kind for the kind shown; undefined for every kind, and null for one it lists no run of by model.
    const of = kind === undefined ? undefined : RUNS_KIND[kind]
    const runs = kind === undefined ? 'run' : KIND_LABEL[kind].replace(/s$/u, '')
    if (models.length === 0) {
        return (
            <Empty size="panel">
                no {runs} {ticket === undefined ? '' : `of ${ticket} `}started in these {span}
            </Empty>
        )
    }
    if (models.every((m) => m.model === null && m.unread)) {
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
                        <th className="panel-label pb-1.5 pl-3 font-normal">
                            <Hinted hint={MODEL_RUNS_HINT}>runs</Hinted>
                        </th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">replies</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">spent</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal whitespace-nowrap">
                            <Hinted hint={PER_RUN_HINT}>per run</Hinted>
                        </th>
                        {ticket !== undefined && (
                            <th className="panel-label pb-1.5 pl-3 font-normal whitespace-nowrap">
                                <Hinted hint={WORKSPACE_HINT}>workspace per run</Hinted>
                            </th>
                        )}
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {models.map((m) => (
                        <tr key={modelKey(m)} className="text-right" data-testid="spend-model">
                            <th scope="row" className="w-full max-w-0 py-0.5 text-left font-normal">
                                {m.model === null ? (
                                    <Tip fact={unnamedHint(m.unread)}>
                                        <span className="block truncate">
                                            <UnnamedModel unread={m.unread} />
                                        </span>
                                    </Tip>
                                ) : of === null || !listed.has(m.model) ? (
                                    <Tip fact={m.model} mono detail={UNLISTED_HINT}>
                                        <span className="block truncate readout" data-testid="spend-model-unlisted">
                                            {m.model}
                                        </span>
                                    </Tip>
                                ) : (
                                    <Link
                                        to="/workspace/runs"
                                        search={{ model: m.model, kind: of }}
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
                            <td className="pl-3">
                                <CellBar
                                    percent={barPercent(
                                        m.cost_usd,
                                        models.map((n) => n.cost_usd),
                                    )}
                                    valueClassName="w-16 text-right"
                                >
                                    <Cost usd={m.cost_usd} />
                                </CellBar>
                            </td>
                            <td className="readout pl-3">
                                <Cost usd={perRun(m)} />
                            </td>
                            {ticket !== undefined && (
                                <td className="readout pl-3 text-muted-foreground">
                                    <Cost usd={workspacePerRun(m)} />
                                </td>
                            )}
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}

/**
 * How much of what By model shows went on runs whose sessions canopy has yet to read (`unreadShare`): the `unread`
 * row's part, said in the header, since it is often the largest and sits near the end. Nothing when there is none.
 */
function Unread({ share }: { share: number | null }) {
    if (share === null) {
        return null
    }
    return (
        <Tip fact={UNREAD_RUNS_HINT}>
            <span className="readout text-xs text-muted-foreground" data-testid="spend-model-unread">
                {shareText(share)} {UNREAD}
            </span>
        </Tip>
    )
}

/** How many models the rows shown name, the runs no session named one for, `unread` or `none`, not among them. */
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
                        <th className="panel-label pb-1.5 pl-3 font-normal">
                            <Hinted hint={RETURNED_HINT}>returned</Hinted>
                        </th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">
                            <Hinted hint={EST_TOKENS_HINT}>~tokens</Hinted>
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
                            <td className="readout pl-3">
                                <Tipped fact={`in ${tool.runs} runs`}>{tool.calls}</Tipped>
                            </td>
                            <td className={cn('readout pl-3', tool.errors === 0 && 'text-muted-foreground')}>
                                {tool.errors}
                            </td>
                            <td className="pl-3">
                                <CellBar
                                    percent={barPercent(
                                        tool.result_chars,
                                        tools.map((t) => t.result_chars),
                                    )}
                                    valueClassName="readout w-12 text-right"
                                >
                                    {tokenCount(tool.result_chars)}
                                </CellBar>
                            </td>
                            <td className="readout pl-3">{tokenCount(tool.est_tokens)}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}

/**
 * The ticks that ended in the window, side by side: by what they bought, a row per group, and the loop's live ticks by
 * what ended the wait before each, the most common first; a line saying so when none ended. Under them, a link to the
 * ticks page's idle ticks, what idle spend bought.
 */
function Ticks({ found, span }: { found: SpendBreakdown; span: string }) {
    if (found.ticks.every((g) => g.ticks === 0)) {
        return <Empty size="panel">no tick ended in these {span}</Empty>
    }
    return (
        <div className="flex flex-col">
            <div className="grid xl:grid-cols-2">
                <CountTable
                    name="bought"
                    hint={BOUGHT_HINT}
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
                {found.woken.length === 0 ? (
                    <Empty size="panel">no tick canopy loop ran in these {span}</Empty>
                ) : (
                    <CountTable
                        name="woken by"
                        hint={WOKEN_HINT}
                        rows={found.woken.map((w) => ({
                            key: w.by,
                            label: w.by,
                            ticks: w.ticks,
                            usd: w.cost_usd,
                            without: w.without_overseer,
                        }))}
                        testId="spend-woken-table"
                    />
                )}
            </div>
            <p className="border-t px-3 py-2 text-xs text-muted-foreground">
                <Link
                    to="/workspace/ticks"
                    search={{ idle: true }}
                    className="text-accent hover:underline"
                    data-testid="spend-idle-link"
                >
                    Open the idle ticks
                </Link>
                , newest first, to see what idle spend bought.
            </p>
        </div>
    )
}

/**
 * Idle ticks' share of the live overseer's spend, the Ticks panel's readout, what it counts on hover. Nothing when the
 * overseer spent nothing, so there is nothing to share.
 */
function IdleShare({ share }: { share: number | null }) {
    if (share === null) {
        return null
    }
    return (
        <Tip fact="Idle ticks' share of the live overseer's spend: what went on deciding there was nothing to do">
            <span className="readout text-xs text-muted-foreground" data-testid="spend-idle-share">
                {shareText(share)} idle
            </span>
        </Tip>
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
    const tiles: ReadoutTile[] = [
        {
            key: 'canopy',
            label: "canopy's runs",
            hint: SESSIONS_CANOPY_HINT,
            value: <SessionsShare share={sessions.canopy} />,
        },
        {
            key: 'outside',
            label: 'outside canopy',
            hint: SESSIONS_OUTSIDE_HINT,
            value: <SessionsShare share={sessions.outside} />,
        },
    ]
    const spent = sessions.directories.map((d) => d.cost_usd)
    return (
        <div className="flex flex-col gap-3 p-3">
            <ReadoutTiles tiles={tiles} testId="spend-sessions" />
            {sessions.directories.length > 0 && (
                <table className="w-full border-collapse text-sm" data-testid="spend-sessions-table">
                    <thead>
                        <tr className="text-right">
                            <th className="panel-label pb-1.5 text-left font-normal">outside canopy, by directory</th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">sessions</th>
                            <th className="panel-label pb-1.5 pl-3 font-normal">spent</th>
                        </tr>
                    </thead>
                    <tbody className="font-mono text-xs">
                        {sessions.directories.map((d) => (
                            <tr key={d.directory} className="text-right" data-testid="spend-sessions-directory">
                                <th scope="row" className="w-full max-w-0 py-0.5 text-left font-normal">
                                    <Clipped text={d.directory} mono className="block" />
                                </th>
                                <td className="readout pl-3">{d.sessions}</td>
                                <td className="pl-3">
                                    <CellBar percent={barPercent(d.cost_usd, spent)} valueClassName="w-16 text-right">
                                        <Cost usd={d.cost_usd} />
                                    </CellBar>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
            <p className="text-xs text-muted-foreground">
                A subagent&apos;s session counts with the session it ran for; another workspace&apos;s runs are outside.
            </p>
        </div>
    )
}

/** A share of the sessions as its tile says it: what they cost, then how many there were, muted. */
function SessionsShare({ share }: { share: SpendShare }) {
    return (
        <>
            <Cost usd={share.cost_usd} />{' '}
            <span className="text-xs text-muted-foreground">in {counted(share.sessions, 'session')}</span>
        </>
    )
}

/**
 * Rows of a label, under `name`, what `hint` says on hover, a tick count, what those ticks' overseers cost, and how
 * many ran no overseer: the harness left it nothing to judge, or the tick halted before it, so each cost nothing.
 */
function CountTable({
    name,
    hint,
    rows,
    testId,
}: {
    name: string
    hint: string
    rows: { key: string; label: string; hint?: string; ticks: number; usd: number | null; without: number }[]
    testId: string
}) {
    return (
        <div className="p-3">
            <table className="border-collapse text-sm" data-testid={testId}>
                <thead>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">
                            <Hinted hint={hint}>{name}</Hinted>
                        </th>
                        <th className="panel-label pb-1.5 pl-6 font-normal">ticks</th>
                        <th className="panel-label pb-1.5 pl-6 font-normal">spent</th>
                        <th className="panel-label pb-1.5 pl-6 font-normal whitespace-nowrap">
                            <Hinted hint={NO_OVERSEER_HINT}>no overseer</Hinted>
                        </th>
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {rows.map((row) => (
                        <tr key={row.key} className="text-right" data-testid={`${testId}-${row.key}`}>
                            <th scope="row" className="py-0.5 text-left font-normal">
                                <Hinted hint={row.hint}>{row.label}</Hinted>
                            </th>
                            <td className="readout pl-6">{row.ticks}</td>
                            <td className="readout pl-6">
                                <Cost usd={row.usd} />
                            </td>
                            <td className="readout pl-6">{row.without}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
