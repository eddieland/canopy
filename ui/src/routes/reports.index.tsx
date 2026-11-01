import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import {
    checklistCountsQuery,
    ciReportQuery,
    healthReportQuery,
    monthlyReportQuery,
    plansReportQuery,
    reviewsReportQuery,
    spendBreakdownQuery,
} from '@/api/queries'
import type { ReportKind, ReportModel, ReportMonth, ReportTicket } from '@/api/types'
import { CellBar } from '@/components/cell-bar'
import { ChartTable } from '@/components/chart-table'
import { Cost } from '@/components/cost'
import { DayChart, DayChartLegend } from '@/components/day-chart'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll, PanelSkeleton } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { Sparkline } from '@/components/sparkline'
import type { SparkPoint } from '@/components/sparkline'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Clipped, Hinted, Tip, Tipped } from '@/components/tip'
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
    medianText,
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

// The column names of a table in a padded scrolling region, as the spend page's: the region's top padding is the
// head's cells', so the rows scrolling under the sticky head never show above it.
const PADDED_HEAD = 'sticky top-0 bg-surface [&_th]:pt-3'
const HEAD = 'panel-label pb-1.5 pl-3 font-normal whitespace-nowrap'

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
 * A month's name as the first cell of its row in Delivery: a link that shows the month in detail below, marked while
 * it does, which the month chart's bars do too, for the mouse.
 */
function MonthCell({ month, picked }: { month: string; picked: string | undefined }) {
    return (
        <th scope="row" className="py-1 text-left font-normal whitespace-nowrap">
            <Link
                to="/reports"
                search={(prev) => ({ ...prev, month })}
                resetScroll={false}
                aria-current={month === picked ? 'true' : undefined}
                className={cn(
                    'rounded-sm px-1 font-sans text-accent underline-offset-4 hover:underline',
                    'aria-[current=true]:bg-accent/16 aria-[current=true]:text-foreground',
                )}
            >
                {monthLabel(month)}
            </Link>
        </th>
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
                <table className="w-full border-collapse text-sm" data-testid="reports-month-table">
                    <thead className="sticky top-0 bg-surface">
                        <tr className="text-right">
                            <th className="panel-label pb-1.5 text-left font-normal">month</th>
                            <th className={HEAD}>spent</th>
                            <th className={HEAD}>runs</th>
                            <th className={HEAD}>
                                <Hinted hint={SENT_HINT}>sent</Hinted>
                            </th>
                            <th className={HEAD}>
                                <Hinted hint={WROTE_HINT}>wrote</Hinted>
                            </th>
                            <th className={HEAD}>
                                <Hinted hint={CACHE_HINT}>cache hit</Hinted>
                            </th>
                            <th className={HEAD}>
                                <Hinted hint={FAILED_HINT}>failed</Hinted>
                            </th>
                            <th className={HEAD}>
                                <Hinted hint={GREEN_FIRST_HINT}>green first</Hinted>
                            </th>
                            <th className={HEAD}>landed</th>
                            <th className={HEAD}>closed</th>
                            <th className={HEAD}>
                                <Hinted hint={PRS_HINT}>PRs</Hinted>
                            </th>
                            <th className={HEAD}>
                                <Hinted hint={PER_LANDED_HINT}>per landed</Hinted>
                            </th>
                        </tr>
                    </thead>
                    <tbody className="font-mono text-xs">
                        {months.toReversed().map((m, i, newest) => {
                            // The month before is the next row down.
                            const before = newest[i + 1]
                            return (
                                <tr key={m.month} className="text-right" data-testid="reports-month">
                                    <th scope="row" className="py-0.5 text-left font-sans font-normal">
                                        {monthLabel(m.month)}
                                    </th>
                                    <Readout hint={monthChange(m.cost_usd, before, (b) => b.cost_usd)}>
                                        <Cost usd={m.cost_usd} />
                                    </Readout>
                                    <Readout>{m.runs}</Readout>
                                    <Readout>{tokenCount(sentTokens(m.tokens))}</Readout>
                                    <Readout>{tokenCount(wroteTokens(m.tokens))}</Readout>
                                    <Readout>{shareText(m.tokens.cache_hit)}</Readout>
                                    <Readout hint={failedHint(m)}>{failedText(m)}</Readout>
                                    <Readout hint={greenFirstHint(m)}>{greenFirstText(m)}</Readout>
                                    <Readout>{m.landed.length}</Readout>
                                    <Readout>{m.closed}</Readout>
                                    <Readout>{m.pull_requests}</Readout>
                                    <Readout hint={monthChange(m.per_landed_usd, before, (b) => b.per_landed_usd)}>
                                        <Cost usd={m.per_landed_usd} />
                                    </Readout>
                                </tr>
                            )
                        })}
                    </tbody>
                </table>
            </ChartTable>
        </div>
    )
}

/** A number in a table's row, right aligned, with what it ran on, if said, in its tip. */
function Readout({ children, hint }: { children: ReactNode; hint?: string | undefined }) {
    return (
        <td className="readout pl-3">
            <Tipped fact={hint}>{children}</Tipped>
        </td>
    )
}

/**
 * Every month: the medians of what each landed ticket took, and of its first reviews' waits, drawn across the months,
 * a sparkline each over the table, a month's figure on its point's hover with, for a time, how many ran on GitHub's
 * clock, or how many first reviews; then the table, the newest month first, which a screen reader reads, each month a
 * link that picks it.
 */
function Delivery({ months, picked }: { months: readonly ReportMonth[]; picked: string | undefined }) {
    // Each trend's figure beside its name is the latest month's, as the line ends on it.
    const latest = months.at(-1)
    return (
        <div className="flex flex-col">
            <ul
                className="grid grid-cols-2 gap-x-6 gap-y-3 p-3 @xl:grid-cols-3 @3xl:grid-cols-5"
                data-testid="reports-trends"
            >
                {DELIVERY_TRENDS.map((trend) => (
                    <li
                        key={trend.key}
                        className="flex min-w-0 flex-col gap-1"
                        data-testid={`reports-trend-${trend.key}`}
                    >
                        <span className="flex items-baseline justify-between gap-2">
                            <span className="panel-label">
                                <Hinted hint={TREND_HINT[trend.key]}>{trend.label}</Hinted>
                            </span>
                            <span className="readout text-xs text-muted-foreground">
                                {latest === undefined ? '–' : trend.text(trend.value(latest))}
                            </span>
                        </span>
                        <Sparkline
                            dots
                            points={months.map((m) => ({
                                key: m.month,
                                value: trend.value(m),
                                hint: trendPointHint(m, trend),
                            }))}
                            testId={`reports-trend-${trend.key}-line`}
                        />
                    </li>
                ))}
            </ul>
            <DeliveryTable months={months} picked={picked} />
        </div>
    )
}

/**
 * Every month, the newest first: the tickets it landed, the medians of what each took, and the median wait of the
 * first reviews that came in it, with how many on hover.
 */
function DeliveryTable({ months, picked }: { months: readonly ReportMonth[]; picked: string | undefined }) {
    return (
        <PanelScroll label="Delivery" className="px-3 pb-3">
            <table className="border-collapse text-sm" data-testid="reports-delivery-table">
                <thead className={PADDED_HEAD}>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">month</th>
                        <th className={HEAD}>landed</th>
                        <th className={HEAD}>
                            <Hinted hint={ITERATIONS_HINT}>iterations</Hinted>
                        </th>
                        <th className={HEAD}>
                            <Hinted hint={COMMENTS_HINT}>PR comments</Hinted>
                        </th>
                        <th className={HEAD}>
                            <Hinted hint={TO_LAND_HINT}>to land</Hinted>
                        </th>
                        <th className={HEAD}>
                            <Hinted hint={WAIT_HINT}>review wait</Hinted>
                        </th>
                        <th className={HEAD}>
                            <Hinted hint={FIRST_REVIEW_HINT}>first review</Hinted>
                        </th>
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {months.toReversed().map((m) => (
                        <tr key={m.month} className="text-right" data-testid="reports-delivery-month">
                            <MonthCell month={m.month} picked={picked} />
                            <Readout>{m.landed.length}</Readout>
                            <Readout>{medianText(m.median_iterations ?? null)}</Readout>
                            <Readout>{medianText(m.median_pr_comments ?? null)}</Readout>
                            <Readout hint={clockShare(m, 'to land')}>
                                {hoursText(m.median_hours_to_land ?? null)}
                            </Readout>
                            <Readout hint={clockShare(m, 'review wait')}>
                                {hoursText(m.median_review_wait_hours ?? null)}
                            </Readout>
                            <Readout
                                hint={m.first_reviews === 0 ? undefined : counted(m.first_reviews, 'first review')}
                            >
                                {hoursText(m.median_first_review_hours ?? null)}
                            </Readout>
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}

/**
 * The picked month's kinds of run: their runs, cost, and tokens; and under them the sessions outside canopy, as of
 * `readAt`, when the runtime's sessions were last read.
 */
function Kinds({ month, readAt }: { month: ReportMonth; readAt: string | null }) {
    const clock = useClock()
    const outside = month.outside
    if (month.runs === 0 && outside.sessions === 0) {
        return <Empty size="panel">nothing ran in {monthLabel(month.month, 'long')}</Empty>
    }
    return (
        <PanelScroll label="By kind" className="px-3 pb-3">
            <table className="w-full border-collapse text-sm" data-testid="reports-kind-table">
                <thead className={PADDED_HEAD}>
                    <tr className="text-right">
                        <th className="panel-label w-full pb-1.5 text-left font-normal">kind</th>
                        <th className={HEAD}>runs</th>
                        <th className={HEAD}>spent</th>
                        <th className={HEAD}>
                            <Hinted hint={SENT_HINT}>sent</Hinted>
                        </th>
                        <th className={HEAD}>
                            <Hinted hint={WROTE_HINT}>wrote</Hinted>
                        </th>
                        <th className={HEAD}>
                            <Hinted hint={CACHE_HINT}>cache hit</Hinted>
                        </th>
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {month.kinds.map((k: ReportKind) => (
                        <tr key={k.kind} className="text-right" data-testid="reports-kind">
                            <th scope="row" className="py-0.5 text-left font-normal">
                                {k.kind}
                            </th>
                            <Readout>{k.runs}</Readout>
                            <ShareCell
                                cost={k.cost_usd}
                                whole={month.cost_usd}
                                month={month}
                                fill={SERIES.find((s) => s.key === k.kind)?.fill}
                            />
                            <Readout>{tokenCount(sentTokens(k.tokens))}</Readout>
                            <Readout>{tokenCount(wroteTokens(k.tokens))}</Readout>
                            <Readout>{shareText(k.tokens.cache_hit ?? null)}</Readout>
                        </tr>
                    ))}
                    <tr className="border-t border-border text-right" data-testid="reports-outside">
                        <th scope="row" className="py-0.5 text-left font-normal">
                            <Hinted hint={outsideHint(readAt, clock)}>outside canopy</Hinted>
                        </th>
                        <Readout>{outside.sessions}</Readout>
                        <ShareCell
                            cost={outside.cost_usd}
                            whole={month.cost_usd}
                            month={month}
                            fill="bg-spend-outside"
                        />
                        <Readout>{tokenCount(sentTokens(outside.tokens))}</Readout>
                        <Readout>{tokenCount(wroteTokens(outside.tokens))}</Readout>
                        <Readout>{shareText(outside.tokens.cache_hit ?? null)}</Readout>
                    </tr>
                </tbody>
            </table>
        </PanelScroll>
    )
}

/**
 * The picked month's models: what each one's replies cost over every kind of run, the dearest first, then the runs no
 * session named a model for, `unread` and then `none` (`UnnamedModel`).
 */
function Models({ month }: { month: ReportMonth }) {
    // What every row cost together, the runs no session named a model for among them: the share's whole.
    const modelsCost = month.models.reduce((total, m) => total + (m.cost_usd ?? 0), 0)
    if (month.models.length === 0) {
        return <Empty size="panel">nothing ran in {monthLabel(month.month, 'long')}</Empty>
    }
    return (
        <PanelScroll label="By model" className="max-h-96 px-3 pb-3">
            <table className="w-full border-collapse text-sm" data-testid="reports-model-table">
                <thead className={PADDED_HEAD}>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">model</th>
                        <th className={HEAD}>runs</th>
                        <th className={HEAD}>replies</th>
                        <th className={HEAD}>spent</th>
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {month.models.map((m: ReportModel) => (
                        <tr key={modelKey(m)} className="text-right" data-testid="reports-model">
                            <th scope="row" className="w-full max-w-0 py-0.5 text-left font-normal">
                                {m.model === null ? (
                                    <Tip fact={unnamedHint(m.unread)}>
                                        <span className="block truncate">
                                            <UnnamedModel unread={m.unread} />
                                        </span>
                                    </Tip>
                                ) : (
                                    <Clipped text={m.model} className="block readout" />
                                )}
                            </th>
                            <Readout>{m.runs}</Readout>
                            <td className={cn('readout pl-3', m.model === null && 'text-muted-foreground')}>
                                {m.model === null ? '–' : m.replies}
                            </td>
                            <ShareCell cost={m.cost_usd} whole={modelsCost} month={month} />
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}

/**
 * A cost with a bar of its share of the month's `whole` after it, in its series' `fill` (`CellBar`), and the share in
 * words on its hover: `51% of October 2026`. The rows of By kind and By model sum to the month, so the bar is the
 * share of it, not of the largest row.
 */
function ShareCell({
    cost,
    whole,
    month,
    fill,
}: {
    cost: number | null
    whole: number | null
    month: ReportMonth
    fill?: string | undefined
}) {
    const share = monthShare(cost, whole)
    const bar = (
        <CellBar percent={share} fill={fill} valueClassName="readout w-16 text-right">
            <Cost usd={cost} />
        </CellBar>
    )
    return (
        <td className="pl-3">
            <Tipped fact={cost === null ? undefined : `${Math.round(share)}% of ${monthLabel(month.month, 'long')}`}>
                {bar}
            </Tipped>
        </td>
    )
}

/** The tickets the picked month landed, the latest first, with what each took. */
function Landed({ month }: { month: ReportMonth }) {
    if (month.landed.length === 0) {
        return <Empty size="panel">no tickets landed in {monthLabel(month.month, 'long')}</Empty>
    }
    return (
        <PanelScroll label="Landed" className="max-h-[32rem] px-3 pb-3">
            <table className="w-full border-collapse text-sm" data-testid="reports-landed-table">
                <thead className={PADDED_HEAD}>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">ticket</th>
                        <th className={HEAD}>
                            <Hinted hint={ITERATIONS_HINT}>iterations</Hinted>
                        </th>
                        <th className={HEAD}>
                            <Hinted hint={COMMENTS_HINT}>PR comments</Hinted>
                        </th>
                        <th className={HEAD}>
                            <Hinted hint={REVIEWS_HINT}>reviews</Hinted>
                        </th>
                        <th className={HEAD}>
                            <Hinted hint={TO_LAND_HINT}>to land</Hinted>
                        </th>
                        <th className={HEAD}>
                            <Hinted hint={WAIT_HINT}>review wait</Hinted>
                        </th>
                        <th className={HEAD}>spent</th>
                        <th className={cn(HEAD, 'text-left')}>pull requests</th>
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {month.landed.map((t: ReportTicket) => (
                        <tr key={t.key} className="text-right" data-testid="reports-landed-ticket">
                            <th scope="row" className="w-full max-w-0 py-1 text-left font-normal">
                                <span className="flex min-w-0 items-baseline gap-2">
                                    <TicketLink ticketKey={t.key} className="shrink-0" />
                                    <TicketTitle title={t.title ?? null} className="font-sans font-normal" />
                                </span>
                            </th>
                            <Readout>{t.iterations}</Readout>
                            <Readout>{t.pr_comments}</Readout>
                            <Readout>
                                {t.reviews}
                                {t.changes_requested > 0 && (
                                    <span className="text-status-blocked"> ({t.changes_requested})</span>
                                )}
                            </Readout>
                            <Readout hint={toLandHint(t)}>{hoursText(t.hours_to_land ?? null)}</Readout>
                            <Readout hint={reviewWaitHint(t)}>{hoursText(t.review_wait_hours ?? null)}</Readout>
                            <td className="pl-3">
                                <CellBar
                                    percent={barPercent(
                                        t.cost_usd,
                                        month.landed.map((l) => l.cost_usd),
                                    )}
                                    valueClassName="readout w-16 text-right"
                                >
                                    <Cost usd={t.cost_usd} />
                                </CellBar>
                            </td>
                            <td className="pl-3 text-left">
                                <span className="flex flex-col items-start">
                                    {t.pull_requests.map((url) => (
                                        <PullRequestLink key={url} url={url} />
                                    ))}
                                </span>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}
