import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import {
    checklistCountsQuery,
    ciReportQuery,
    healthReportQuery,
    monthlyReportQuery,
    plansReportQuery,
    reviewsReportQuery,
    spendBreakdownQuery,
} from '@/api/queries'
import type { ReportKind, ReportModel, ReportMonth, ReportTicket, ReportTokens } from '@/api/types'
import { ChartTable } from '@/components/chart-table'
import { Cost } from '@/components/cost'
import { DayChart, DayChartLegend } from '@/components/day-chart'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelSkeleton } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { ReportTable } from '@/components/report-table'
import type { ReportColumn } from '@/components/report-table'
import { Sparkline } from '@/components/sparkline'
import type { SparkPoint } from '@/components/sparkline'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Clipped, Hinted, Tip } from '@/components/tip'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { UnnamedModel } from '@/components/unnamed-model'
import { barPercent } from '@/lib/chart'
import { checklistLine } from '@/lib/checklist'
import { ciLine } from '@/lib/ci'
import { useClock } from '@/lib/clock'
import { counted } from '@/lib/descriptions'
import { countSum, healthLine } from '@/lib/health'
import { unnamedHint } from '@/lib/models'
import { plansLine } from '@/lib/plan-report'
import { REPORT_PAGES } from '@/lib/report-pages'
import type { ReportPage } from '@/lib/report-pages'
import type { DeliveryTrend } from '@/lib/reports'
import {
    clockShare,
    DEFAULT_MONTHS,
    DELIVERY_TRENDS,
    failedHint,
    failedText,
    fittedMonths,
    greenFirstHint,
    greenFirstText,
    hoursText,
    monthBars,
    monthChange,
    monthLabel,
    MONTH_SERIES,
    monthShare,
    outsideHint,
    pickedMonth,
    REPORT_SPANS,
    reportLine,
    reportMonth,
    reportSpan,
    reviewWaitHint,
    sentTokens,
    sinceText,
    toLandHint,
    trendPointHint,
    wroteTokens,
} from '@/lib/reports'
import { reviewsLine } from '@/lib/review-report'
import { modelKey, SERIES, shareText, spendLine } from '@/lib/spend'
import { tokenCount } from '@/lib/transcript'
import { cn } from '@/lib/utils'

interface ReportsSearch {
    months?: number | undefined
    month?: string | undefined
}

// What the page shows on every visit, on its title's hover: its description is the latest month's state.
const HELP =
    "What canopy cost and got done: each report page's last 30 days on its card, then each calendar month's dollars " +
    'and tokens by kind of run and by model, how much of what the models were sent came from the cache, and the ' +
    'tickets the loop marked done as merged, with the worker runs, PR comments, and time each took. Click a month, ' +
    'in the chart or in Delivery, for its detail.'

// The window each report page's card reads, the longest every page offers.
const CARD_DAYS = 30

// What each column counts, on hover.
const SENT_HINT = 'What the model calls were sent: new input, and what they read from or wrote to the cache'
const WROTE_HINT = 'What the models wrote, their reasoning included'
const CACHE_HINT = 'The share of what was sent that was read from the cache, which costs a fraction of new input'
const PER_LANDED_HINT = "The month's whole cost, the overseer's and chores' included, over the tickets it landed"
const PRS_HINT = 'The PRs a run first named in the month'
const FAILED_HINT =
    'Runs of every kind that started in the month and ended failed, as the Health page counts them. Hover a figure ' +
    'for how many ended, and what the failures cost'
const GREEN_FIRST_HINT =
    'The share of PR heads first checked in the month whose first run of every check was not red, as the CI page ' +
    'counts them. Hover a figure for how many'
const FIRST_REVIEW_HINT =
    "From when a PR began waiting on a review to its first review, on GitHub's clock, the median of every first " +
    'review that came in the month, landed or not, as the Reviews page times them'
const ITERATIONS_HINT = 'Worker runs, implement and resume, that started before the ticket landed'
const COMMENTS_HINT = "Comments on its PRs from people other than the PR's author; canopy posts as the author"
const REVIEWS_HINT = "Reviews of its PRs from people other than the PR's author, then how many asked for changes"
const TO_LAND_HINT =
    "From its first worker run to its PR's merge, as GitHub timed it; where canopy kept no merge time, to the tick " +
    'that marked it done. Hover a figure for which'
const WAIT_HINT =
    'From when its PR began waiting on a review, as GitHub timed it, to the first review after it; where canopy kept ' +
    'no ready time, from the end of its first worker run that ended done. Hover a figure for which'

// What each of Delivery's trends counts, on its name's hover, by its key.
const TREND_HINT: Record<string, string> = {
    iterations: ITERATIONS_HINT,
    comments: COMMENTS_HINT,
    'to-land': TO_LAND_HINT,
    'review-wait': WAIT_HINT,
    'first-review': FIRST_REVIEW_HINT,
}

// A row of the month table: the month, and the month before it, which its tips compare it with.
interface MonthRow {
    month: ReportMonth
    before: ReportMonth | undefined
}

// A row of By kind: a kind of run, or the sessions outside canopy, ruled off under them; its test id says which.
interface KindRow {
    key: string
    name: string
    hint?: string
    runs: number
    cost: number | null
    tokens: ReportTokens
    fill: string | undefined
    outside: boolean
}

// A row of By model: the model, and its cost, as a share of the month's.
type ModelShare = ReportModel & { cost: number | null }

/**
 * The reports' home: a card for each report page, its last 30 days at a glance, then what each local calendar month
 * cost, in dollars and tokens, by kind and by model, and what it got done: the tickets the loop landed, with their
 * worker runs, PR comments, reviews, and how long they took. With no `?months=`, it opens on the months from the first
 * that holds anything, a year at most (`fittedMonths`); `?months=` is a span of 6, 12, or 24 months, each drawn whole,
 * and `?month=` the month shown in detail, the latest when absent.
 */
export const Route = createFileRoute('/reports/')({
    validateSearch: (search: Record<string, unknown>): ReportsSearch => ({
        months: reportSpan(search['months']),
        month: reportMonth(search['month']),
    }),
    component: ReportsPage,
})

function ReportsPage() {
    const search = Route.useSearch()
    const navigate = Route.useNavigate()
    const span = search.months ?? DEFAULT_MONTHS
    const query = useQuery(monthlyReportQuery(span))
    const read = query.data?.months
    // With no span picked, the months from the first that holds anything; a span picked draws every one of it.
    const months = read === undefined || search.months !== undefined ? read : fittedMonths(read)
    const picked = months === undefined ? undefined : pickedMonth(months, search.month)
    const failed = months === undefined && query.error !== null
    const pick = (month: string) => {
        void navigate({ search: (prev) => ({ ...prev, month }), resetScroll: false })
    }
    return (
        <>
            <PageHeader
                title="Reports"
                help={HELP}
                controls={
                    <ToggleGroup
                        type="single"
                        // No span pressed while the page fits the journal.
                        value={search.months === undefined ? '' : String(span)}
                        aria-label="Span"
                        onValueChange={(value) => {
                            // Pressing the span shown lets it go, and the page fits the journal again.
                            const n = REPORT_SPANS.find((s) => String(s) === value)
                            void navigate({ search: (prev) => ({ ...prev, months: n }) })
                        }}
                    >
                        {REPORT_SPANS.map((n) => (
                            <ToggleGroupItem key={n} value={String(n)} data-testid={`reports-span-${n}`}>
                                {n} months
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                }
            >
                {months === undefined ? (query.isPending ? 'reading the months' : null) : reportLine(months)}
            </PageHeader>
            <ReportCards />
            <Panel data-testid="reports-months">
                <PanelHeader label="Month by month">
                    <span className="readout text-xs text-muted-foreground" data-testid="reports-months-span">
                        {months === undefined ? '' : spanText(months, search.months)}
                    </span>
                </PanelHeader>
                {months === undefined ? (
                    <PanelLoading query={query} rows={6} className="min-h-72" />
                ) : (
                    <Months months={months} picked={picked?.month} onPick={pick} />
                )}
            </Panel>
            {!failed && (
                <>
                    <Panel data-testid="reports-delivery">
                        <PanelHeader label="Delivery">
                            <span className="readout text-xs text-muted-foreground">medians by month</span>
                        </PanelHeader>
                        {months === undefined ? (
                            <PanelSkeleton rows={6} className="min-h-40" />
                        ) : (
                            <Delivery months={months} picked={picked?.month} />
                        )}
                    </Panel>
                    <div className="grid gap-6 xl:grid-cols-2">
                        <Panel data-testid="reports-kinds">
                            <PanelHeader label="By kind">
                                <MonthName month={picked} />
                            </PanelHeader>
                            {picked === undefined ? (
                                <PanelSkeleton rows={6} className="min-h-40" />
                            ) : (
                                <Kinds month={picked} readAt={query.data?.sessions_read_at ?? null} />
                            )}
                        </Panel>
                        <Panel data-testid="reports-models">
                            <PanelHeader label="By model">
                                <MonthName month={picked} />
                            </PanelHeader>
                            {picked === undefined ? (
                                <PanelSkeleton rows={4} className="min-h-40" />
                            ) : (
                                <Models month={picked} />
                            )}
                        </Panel>
                    </div>
                    <Panel data-testid="reports-landed">
                        <PanelHeader label="Landed">
                            <span className="readout text-xs text-muted-foreground">
                                {picked === undefined
                                    ? ''
                                    : `${monthLabel(picked.month, 'long')} · ${picked.landed.length}`}
                            </span>
                        </PanelHeader>
                        {picked === undefined ? (
                            <PanelSkeleton rows={5} className="min-h-32" />
                        ) : (
                            <Landed month={picked} />
                        )}
                    </Panel>
                </>
            )}
        </>
    )
}

// The month chart's span, in its header: where a fitted one starts, `since April 2026`, or a picked one's length.
function spanText(months: readonly ReportMonth[], picked: number | undefined): string {
    return picked === undefined ? sinceText(months) : counted(months.length, 'month')
}

/**
 * A card for each page under Reports, in the nav's order, each a link to the page over the same 30 days: its name,
 * its description line as the page itself gives it (`$41.20 over 30 days · 3 tickets done`), and a sparkline of its
 * by-day series where it has one. The nav's hint for the page is the card's hover. Each reads its own report, so one
 * slow or failed read leaves the others standing.
 */
function ReportCards() {
    const spend = useQuery(spendBreakdownQuery({ days: CARD_DAYS }))
    const checklist = useQuery(checklistCountsQuery(CARD_DAYS))
    const health = useQuery(healthReportQuery(CARD_DAYS))
    const ci = useQuery(ciReportQuery(CARD_DAYS))
    const reviews = useQuery(reviewsReportQuery(CARD_DAYS))
    const plans = useQuery(plansReportQuery(CARD_DAYS))
    const [spendPage, checklistPage, healthPage, ciPage, reviewsPage, plansPage] = REPORT_PAGES
    return (
        <nav aria-label="Report pages" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="reports-cards">
            <ReportCard
                page={spendPage}
                query={spend}
                line={spendLine}
                series={(found) => found.per_day.map((day) => ({ key: day.day, value: day.costs.total ?? 0 }))}
            />
            <ReportCard
                page={checklistPage}
                query={checklist}
                line={(found) => checklistLine(found.items, found.days)}
            />
            <ReportCard
                page={healthPage}
                query={health}
                line={healthLine}
                series={(found) => found.per_day.map((day) => ({ key: day.day, value: countSum(day.failed) }))}
            />
            <ReportCard
                page={ciPage}
                query={ci}
                line={ciLine}
                series={(found) => found.per_day.map((day) => ({ key: day.day, value: sum(day.red) }))}
            />
            <ReportCard
                page={reviewsPage}
                query={reviews}
                line={reviewsLine}
                series={(found) => found.per_day.map((day) => ({ key: day.day, value: sum(day.first_reviews) }))}
            />
            <ReportCard page={plansPage} query={plans} line={plansLine} />
        </nav>
    )
}

// A list of counts summed.
function sum(counts: readonly number[]): number {
    return counts.reduce((total, n) => total + n, 0)
}

/**
 * One report page's card: its name over its description line, read from `query`, and its by-day `series` as a
 * sparkline, if it has one. While the report is read, a line's skeleton holds the line's place; a read that failed
 * says so in the line, and the page itself says why.
 */
function ReportCard<T>({
    page,
    query,
    line,
    series,
}: {
    page: ReportPage
    query: UseQueryResult<T>
    line: (found: T) => string
    series?: (found: T) => SparkPoint[]
}) {
    const { data } = query
    const key = page.to.replace('/reports/', '')
    return (
        <Link
            to={page.to}
            search={{ days: CARD_DAYS }}
            title={page.hint}
            className={cn(
                'flex min-w-0 flex-col gap-1.5 rounded-md border border-edge bg-surface p-3 shadow-panel',
                'hover:bg-surface-raised',
            )}
            data-testid={`reports-card-${key}`}
        >
            <span className="panel-label text-foreground">{page.label}</span>
            <span className="min-h-10 text-sm text-foreground" data-testid={`reports-card-${key}-line`}>
                {data === undefined ? (
                    query.isPending ? (
                        <Skeleton className="my-0.5 h-4 w-48" />
                    ) : (
                        <span className="text-muted-foreground">not read: open the page for why</span>
                    )
                ) : (
                    line(data)
                )}
            </span>
            {series !== undefined && data !== undefined && (
                <Sparkline points={series(data)} testId={`reports-card-${key}-trend`} />
            )}
        </Link>
    )
}

/** The picked month's name, in a panel's header. */
function MonthName({ month }: { month: ReportMonth | undefined }) {
    return (
        <span className="readout text-xs text-muted-foreground">
            {month === undefined ? '' : monthLabel(month.month, 'long')}
        </span>
    )
}

/**
 * Every month as the month chart: the spend chart at a month's pitch (`monthBars`), a bar of what each cost stacked
 * by kind, the sessions outside canopy on top, the picked month marked and a click on another picking it, the legend
 * under it, then the same months as a table, folded: what each cost, against the month before on hover, its runs,
 * tokens, failed runs, share of PR heads green first time, and output. A span where nothing reported a cost says so
 * in place of the chart and its legend.
 */
function Months({
    months,
    picked,
    onPick,
}: {
    months: readonly ReportMonth[]
    picked: string | undefined
    onPick: (month: string) => void
}) {
    const bars = monthBars(months)
    const spent = bars.some((bar) => bar.total > 0)
    return (
        <div className="flex flex-col gap-4 p-3">
            {spent ? (
                <>
                    {/* Measured afresh for each span: another count of bars is another pitch. */}
                    <DayChart key={bars.length} bars={bars} testId="reports" marked={picked} onPick={onPick} />
                    <DayChartLegend series={MONTH_SERIES} testId="reports" />
                </>
            ) : (
                <Empty size="panel">no run reported a cost in these months</Empty>
            )}
            <ChartTable
                what={counted(months.length, 'month')}
                label="Month by month"
                className="max-h-96 overflow-x-auto"
                testId="reports-month-scroll"
            >
                <ReportTable
                    rows={months.toReversed().map((month, n, newest) => ({ month, before: newest[n + 1] }))}
                    columns={MONTH_COLUMNS}
                    rowKey={(row) => row.month.month}
                    label="Month by month"
                    scroll={false}
                    testId="reports-month-table"
                    rowTestId="reports-month"
                />
            </ChartTable>
        </div>
    )
}

/**
 * The month table's columns: the month, what it cost, against the month before on hover, its runs, its tokens, its
 * failed runs, its share of PR heads green first time, and its output.
 */
const MONTH_COLUMNS: ReportColumn<MonthRow>[] = [
    { key: 'month', kind: 'name', label: 'month', cell: ({ month: m }) => monthLabel(m.month) },
    {
        key: 'spent',
        kind: 'figure',
        label: 'spent',
        cell: ({ month: m }) => <Cost usd={m.cost_usd} />,
        tip: ({ month: m, before }) => monthChange(m.cost_usd, before, (b) => b.cost_usd),
    },
    { key: 'runs', kind: 'figure', label: 'runs', cell: ({ month: m }) => m.runs },
    {
        key: 'sent',
        kind: 'figure',
        label: 'sent',
        hint: SENT_HINT,
        cell: ({ month: m }) => tokenCount(sentTokens(m.tokens)),
    },
    {
        key: 'wrote',
        kind: 'figure',
        label: 'wrote',
        hint: WROTE_HINT,
        cell: ({ month: m }) => tokenCount(wroteTokens(m.tokens)),
    },
    {
        key: 'cache',
        kind: 'figure',
        label: 'cache hit',
        hint: CACHE_HINT,
        cell: ({ month: m }) => shareText(m.tokens.cache_hit),
    },
    {
        key: 'failed',
        kind: 'figure',
        label: 'failed',
        hint: FAILED_HINT,
        cell: ({ month: m }) => failedText(m),
        tip: ({ month: m }) => failedHint(m),
    },
    {
        key: 'green-first',
        kind: 'figure',
        label: 'green first',
        hint: GREEN_FIRST_HINT,
        cell: ({ month: m }) => greenFirstText(m),
        tip: ({ month: m }) => greenFirstHint(m),
    },
    { key: 'landed', kind: 'figure', label: 'landed', cell: ({ month: m }) => m.landed.length },
    { key: 'closed', kind: 'figure', label: 'closed', cell: ({ month: m }) => m.closed },
    { key: 'prs', kind: 'figure', label: 'PRs', hint: PRS_HINT, cell: ({ month: m }) => m.pull_requests },
    {
        key: 'per-landed',
        kind: 'figure',
        label: 'per landed',
        hint: PER_LANDED_HINT,
        cell: ({ month: m }) => <Cost usd={m.per_landed_usd} />,
        tip: ({ month: m, before }) => monthChange(m.per_landed_usd, before, (b) => b.per_landed_usd),
    },
]

/**
 * Every month, the newest first: the tickets it landed, the medians of what each took, each drawn across the months
 * as a sparkline over its column, a month's figure on its point's hover with, for a time, how many ran on GitHub's
 * clock, or how many first reviews; and the median wait of the first reviews that came in it, with how many on hover.
 * Each month is a link that picks it.
 */
function Delivery({ months, picked }: { months: readonly ReportMonth[]; picked: string | undefined }) {
    return (
        <ReportTable
            rows={months.toReversed()}
            columns={deliveryColumns(months, picked)}
            rowKey={(m) => m.month}
            label="Delivery"
            className="px-3 pb-3"
            testId="reports-delivery-table"
            rowTestId="reports-delivery-month"
        />
    )
}

/** Delivery's columns: the month, a link that picks it, its tickets landed, and a column per trend, its line on top. */
function deliveryColumns(months: readonly ReportMonth[], picked: string | undefined): ReportColumn<ReportMonth>[] {
    return [
        { key: 'month', kind: 'name', label: 'month', cell: (m) => <MonthLink month={m.month} picked={picked} /> },
        { key: 'landed', kind: 'figure', label: 'landed', cell: (m) => m.landed.length },
        ...DELIVERY_TRENDS.map((trend): ReportColumn<ReportMonth> => ({
            key: trend.key,
            kind: 'figure',
            label: trend.label,
            hint: TREND_HINT[trend.key],
            cell: (m) => trend.text(trend.value(m)),
            tip: (m) => trendTip(m, trend),
            over: (
                <Sparkline
                    dots
                    points={months.map((m) => ({
                        key: m.month,
                        value: trend.value(m),
                        hint: trendPointHint(m, trend),
                    }))}
                    testId={`reports-trend-${trend.key}-line`}
                    className="w-32"
                />
            ),
        })),
    ]
}

// A month's median of a trend in Delivery's table, on hover: for a time, how many of its figures ran on GitHub's
// clock; for a median of other figures than the landed tickets', how many, where it has one.
function trendTip(month: ReportMonth, trend: DeliveryTrend): string | undefined {
    if (trend.clock !== undefined) {
        return clockShare(month, trend.clock)
    }
    return trend.value(month) === null ? undefined : trend.of?.(month)
}

/**
 * A month's name as the first cell of its row in Delivery: a link that shows the month in detail below, marked while
 * it does, which the month chart's bars do too, for the mouse.
 */
function MonthLink({ month, picked }: { month: string; picked: string | undefined }) {
    return (
        <Link
            to="/reports"
            search={(prev) => ({ ...prev, month })}
            resetScroll={false}
            aria-current={month === picked ? 'true' : undefined}
            className={cn(
                'rounded-sm px-1 text-accent underline-offset-4 hover:underline',
                'aria-current:bg-accent/16 aria-current:text-foreground',
            )}
        >
            {monthLabel(month)}
        </Link>
    )
}

/**
 * The picked month's kinds of run: their runs, cost, and tokens; and under them, ruled off, the sessions outside
 * canopy, as of `readAt`, when the runtime's sessions were last read.
 */
function Kinds({ month, readAt }: { month: ReportMonth; readAt: string | null }) {
    const clock = useClock()
    const outside = month.outside
    if (month.runs === 0 && outside.sessions === 0) {
        return <Empty size="panel">nothing ran in {monthLabel(month.month, 'long')}</Empty>
    }
    const rows: KindRow[] = [
        ...month.kinds.map((k: ReportKind) => ({
            key: k.kind,
            name: k.kind,
            runs: k.runs,
            cost: k.cost_usd ?? null,
            tokens: k.tokens,
            fill: SERIES.find((s) => s.key === k.kind)?.fill,
            outside: false,
        })),
        {
            key: 'outside',
            name: 'outside canopy',
            hint: outsideHint(readAt, clock),
            runs: outside.sessions,
            cost: outside.cost_usd ?? null,
            tokens: outside.tokens,
            fill: 'bg-spend-outside',
            outside: true,
        },
    ]
    return (
        <ReportTable
            rows={rows}
            columns={kindColumns(month)}
            rowKey={(row) => row.key}
            label="By kind"
            className="px-3 pb-3"
            ruled={(row) => row.outside}
            testId="reports-kind-table"
            rowTestId={(row) => (row.outside ? 'reports-outside' : 'reports-kind')}
        />
    )
}

/** By kind's columns: the kind, its runs, what it cost with a bar of its share of `month`, and its tokens. */
function kindColumns(month: ReportMonth): ReportColumn<KindRow>[] {
    return [
        {
            key: 'kind',
            kind: 'name',
            label: 'kind',
            cell: (row) => (
                <span className="font-mono">
                    <Hinted hint={row.hint}>{row.name}</Hinted>
                </span>
            ),
        },
        { key: 'runs', kind: 'figure', label: 'runs', cell: (row) => row.runs },
        { ...shareColumn<KindRow>(month, month.cost_usd ?? null), fill: (row) => row.fill },
        {
            key: 'sent',
            kind: 'figure',
            label: 'sent',
            hint: SENT_HINT,
            cell: (row) => tokenCount(sentTokens(row.tokens)),
        },
        {
            key: 'wrote',
            kind: 'figure',
            label: 'wrote',
            hint: WROTE_HINT,
            cell: (row) => tokenCount(wroteTokens(row.tokens)),
        },
        {
            key: 'cache',
            kind: 'figure',
            label: 'cache hit',
            hint: CACHE_HINT,
            cell: (row) => shareText(row.tokens.cache_hit ?? null),
        },
    ]
}

/**
 * A `spent` column of a cost with a bar of its share of `month`'s `whole` after it, and the share in words on its
 * hover: `51% of October 2026`. The rows of By kind and By model sum to the month, so the bar is the share of it, not
 * of the largest row.
 */
function shareColumn<T extends { cost: number | null }>(month: ReportMonth, whole: number | null): ReportColumn<T> {
    return {
        key: 'spent',
        kind: 'bar',
        label: 'spent',
        cell: (row) => <Cost usd={row.cost} />,
        bar: (row) => monthShare(row.cost, whole),
        tip: (row) =>
            row.cost === null
                ? undefined
                : `${Math.round(monthShare(row.cost, whole))}% of ${monthLabel(month.month, 'long')}`,
    }
}

/**
 * The picked month's models: what each one's replies cost over every kind of run, the dearest first, then the runs no
 * session named a model for, `unread` and then `none` (`UnnamedModel`).
 */
function Models({ month }: { month: ReportMonth }) {
    if (month.models.length === 0) {
        return <Empty size="panel">nothing ran in {monthLabel(month.month, 'long')}</Empty>
    }
    return (
        <ReportTable
            rows={month.models.map((m: ReportModel) => ({ ...m, cost: m.cost_usd ?? null }))}
            columns={modelColumns(month)}
            rowKey={modelKey}
            label="By model"
            testId="reports-model-table"
            rowTestId="reports-model"
        />
    )
}

/** By model's columns: the model, its runs and replies, and what it cost with a bar of its share of the month's. */
function modelColumns(month: ReportMonth): ReportColumn<ModelShare>[] {
    // What every row cost together, the runs no session named a model for among them: the share's whole.
    const modelsCost = month.models.reduce((total, m) => total + (m.cost_usd ?? 0), 0)
    return [
        {
            key: 'model',
            kind: 'free',
            label: 'model',
            cell: (m) =>
                m.model === null ? (
                    <Tip fact={unnamedHint(m.unread)}>
                        <span className="block truncate">
                            <UnnamedModel unread={m.unread} />
                        </span>
                    </Tip>
                ) : (
                    <Clipped text={m.model} className="block readout" />
                ),
        },
        { key: 'runs', kind: 'figure', label: 'runs', cell: (m) => m.runs },
        {
            key: 'replies',
            kind: 'figure',
            label: 'replies',
            cell: (m) => (m.model === null ? '–' : m.replies),
            tone: (m) => m.model === null && 'text-muted-foreground',
        },
        shareColumn<ModelShare>(month, modelsCost),
    ]
}

/** The tickets the picked month landed, the latest first, with what each took. */
function Landed({ month }: { month: ReportMonth }) {
    if (month.landed.length === 0) {
        return <Empty size="panel">no tickets landed in {monthLabel(month.month, 'long')}</Empty>
    }
    return (
        <ReportTable
            rows={month.landed}
            columns={landedColumns(month.landed)}
            rowKey={(t) => t.key}
            label="Landed"
            className="max-h-[32rem] px-3 pb-3"
            testId="reports-landed-table"
            rowTestId="reports-landed-ticket"
        />
    )
}

/**
 * Landed's columns: the ticket, its iterations, PR comments, reviews and those that asked for changes, how long it
 * took to land and to be reviewed, what it cost with a bar of the dearest's, and its PRs.
 */
function landedColumns(landed: readonly ReportTicket[]): ReportColumn<ReportTicket>[] {
    const spent = landed.map((t) => t.cost_usd)
    return [
        {
            key: 'ticket',
            kind: 'free',
            label: 'ticket',
            cell: (t) => (
                <span className="flex min-w-0 items-baseline gap-2">
                    <TicketLink ticketKey={t.key} className="shrink-0" />
                    <TicketTitle title={t.title ?? null} className="font-normal" />
                </span>
            ),
        },
        { key: 'iterations', kind: 'figure', label: 'iterations', hint: ITERATIONS_HINT, cell: (t) => t.iterations },
        { key: 'comments', kind: 'figure', label: 'PR comments', hint: COMMENTS_HINT, cell: (t) => t.pr_comments },
        {
            key: 'reviews',
            kind: 'figure',
            label: 'reviews',
            hint: REVIEWS_HINT,
            cell: (t) => (
                <>
                    {t.reviews}
                    {t.changes_requested > 0 && <span className="text-status-blocked"> ({t.changes_requested})</span>}
                </>
            ),
        },
        {
            key: 'to-land',
            kind: 'figure',
            label: 'to land',
            hint: TO_LAND_HINT,
            cell: (t) => hoursText(t.hours_to_land ?? null),
            tip: toLandHint,
        },
        {
            key: 'review-wait',
            kind: 'figure',
            label: 'review wait',
            hint: WAIT_HINT,
            cell: (t) => hoursText(t.review_wait_hours ?? null),
            tip: reviewWaitHint,
        },
        {
            key: 'spent',
            kind: 'bar',
            label: 'spent',
            cell: (t) => <Cost usd={t.cost_usd} />,
            bar: (t) => barPercent(t.cost_usd, spent),
        },
        {
            key: 'pull-requests',
            kind: 'word',
            label: 'pull requests',
            cell: (t) => (
                <span className="flex flex-col items-start">
                    {t.pull_requests.map((url) => (
                        <PullRequestLink key={url} url={url} />
                    ))}
                </span>
            ),
        },
    ]
}
