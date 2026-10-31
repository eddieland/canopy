import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { monthlyReportQuery } from '@/api/queries'
import type { ReportKind, ReportModel, ReportMonth, ReportTicket } from '@/api/types'
import { CellBar } from '@/components/cell-bar'
import { Cost } from '@/components/cost'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll, PanelSkeleton } from '@/components/panel'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Clipped, Hinted, Tip, Tipped } from '@/components/tip'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { UnnamedModel } from '@/components/unnamed-model'
import { barPercent } from '@/lib/chart'
import { useClock } from '@/lib/clock'
import {
    clockShare,
    DEFAULT_MONTHS,
    hoursText,
    medianText,
    monthLabel,
    outsideHint,
    pickedMonth,
    REPORT_SPANS,
    reportLine,
    reportMonth,
    reportSpan,
    reviewWaitHint,
    sentTokens,
    toLandHint,
    wroteTokens,
} from '@/lib/reports'
import { unnamedHint } from '@/lib/models'
import { modelKey, shareText } from '@/lib/spend'
import { tokenCount } from '@/lib/transcript'
import { cn } from '@/lib/utils'

interface ReportsSearch {
    months?: number | undefined
    month?: string | undefined
}

// What the page shows on every visit, on its title's hover: its description is the latest month's state.
const HELP =
    'What canopy cost and got done in each calendar month: dollars and tokens by kind of run and by model, how much ' +
    'of what the models were sent came from the cache, and the tickets the loop marked done as merged, with the ' +
    'worker runs, PR comments, and time each took. Pick a month for its detail.'

// What each column counts, on hover.
const SENT_HINT = 'What the model calls were sent: new input, and what they read from or wrote to the cache'
const WROTE_HINT = 'What the models wrote, their reasoning included'
const CACHE_HINT = 'The share of what was sent that was read from the cache, which costs a fraction of new input'
const PER_LANDED_HINT = "The month's whole cost, the overseer's and chores' included, over the tickets it landed"
const PRS_HINT = 'The PRs a run first named in the month'
const ITERATIONS_HINT = 'Worker runs, implement and resume, that started before the ticket landed'
const COMMENTS_HINT = "Comments on its PRs from people other than the PR's author; canopy posts as the author"
const REVIEWS_HINT = "Reviews of its PRs from people other than the PR's author, then how many asked for changes"
const TO_LAND_HINT =
    "From its first worker run to its PR's merge, as GitHub timed it; where canopy kept no merge time, to the tick " +
    'that marked it done. Hover a figure for which'
const WAIT_HINT =
    'From when its PR began waiting on a review, as GitHub timed it, to the first review after it; where canopy kept ' +
    'no ready time, from the end of its first worker run that ended done. Hover a figure for which'

// The column names of a table in a padded scrolling region, as the spend page's: the region's top padding is the
// head's cells', so the rows scrolling under the sticky head never show above it.
const PADDED_HEAD = 'sticky top-0 bg-surface [&_th]:pt-3'
const HEAD = 'panel-label pb-1.5 pl-3 font-normal whitespace-nowrap'

/**
 * What each local calendar month cost, in dollars and tokens, by kind and by model, and what it got done: the tickets
 * the loop landed, with their worker runs, PR comments, reviews, and how long they took. `?months=` is the span, 6 or
 * 24 (a year when absent), and `?month=` the month shown in detail, the latest when absent. The spend page, by day,
 * is under it, at `/reports/spend`, and the checklist's counts, by item, at `/reports/checklist`.
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
    const months = query.data?.months
    const picked = months === undefined ? undefined : pickedMonth(months, search.month)
    const failed = months === undefined && query.error !== null
    return (
        <>
            <PageHeader
                title="Reports"
                help={HELP}
                controls={
                    <ToggleGroup
                        type="single"
                        value={String(span)}
                        aria-label="Span"
                        onValueChange={(value) => {
                            const n = REPORT_SPANS.find((s) => String(s) === value)
                            // Pressing the span shown turns it off: keep it. A year, the default, needs no search.
                            if (n !== undefined) {
                                void navigate({
                                    search: (prev) => ({ ...prev, months: n === DEFAULT_MONTHS ? undefined : n }),
                                })
                            }
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
            <Panel data-testid="reports-months">
                <PanelHeader label="Month by month">
                    <span className="flex flex-wrap items-center gap-x-3">
                        <Link
                            to="/reports/spend"
                            className="text-xs text-accent underline-offset-4 hover:underline"
                            data-testid="reports-spend-link"
                        >
                            Spend by day
                        </Link>
                        <Link
                            to="/reports/checklist"
                            className="text-xs text-accent underline-offset-4 hover:underline"
                            data-testid="reports-checklist-link"
                        >
                            Checklist
                        </Link>
                    </span>
                </PanelHeader>
                {months === undefined ? (
                    <PanelLoading query={query} rows={6} className="min-h-40" />
                ) : (
                    <Months months={months} picked={picked?.month} />
                )}
            </Panel>
            {!failed && (
                <>
                    <Panel data-testid="reports-delivery">
                        <PanelHeader label="Delivery">
                            <span className="readout text-xs text-muted-foreground">median per landed ticket</span>
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

/** The picked month's name, in a panel's header. */
function MonthName({ month }: { month: ReportMonth | undefined }) {
    return (
        <span className="readout text-xs text-muted-foreground">
            {month === undefined ? '' : monthLabel(month.month, 'long')}
        </span>
    )
}

/**
 * A month's name as the first cell of its row: a link that shows the month in detail below, marked while it does. The
 * bar under the cost is the eye's; a screen reader reads the cost.
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

/** Every month, the newest first: what it cost, with a bar against the dearest, its runs, tokens, and output. */
function Months({ months, picked }: { months: readonly ReportMonth[]; picked: string | undefined }) {
    return (
        <PanelScroll label="Month by month" className="px-3 pb-3">
            <table className="w-full border-collapse text-sm" data-testid="reports-month-table">
                <thead className={PADDED_HEAD}>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">month</th>
                        <th className={cn(HEAD, 'w-full text-left')}>spent</th>
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
                    {months.toReversed().map((m) => (
                        <tr key={m.month} className="text-right" data-testid="reports-month">
                            <MonthCell month={m.month} picked={picked} />
                            <td className="pl-3 text-left">
                                <CellBar
                                    percent={barPercent(
                                        m.cost_usd,
                                        months.map((n) => n.cost_usd),
                                    )}
                                    valueClassName="w-20"
                                >
                                    <Cost usd={m.cost_usd} />
                                </CellBar>
                            </td>
                            <Readout>{m.runs}</Readout>
                            <Readout>{tokenCount(sentTokens(m.tokens))}</Readout>
                            <Readout>{tokenCount(wroteTokens(m.tokens))}</Readout>
                            <Readout>{shareText(m.tokens.cache_hit ?? null)}</Readout>
                            <Readout>{m.landed.length}</Readout>
                            <Readout>{m.closed}</Readout>
                            <Readout>{m.pull_requests}</Readout>
                            <td className="readout pl-3">
                                <Cost usd={m.per_landed_usd ?? null} />
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
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

/** Every month, the newest first: the tickets it landed and the medians of what each took. */
function Delivery({ months, picked }: { months: readonly ReportMonth[]; picked: string | undefined }) {
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
                            <td className="readout pl-3">
                                <Cost usd={k.cost_usd ?? null} />
                            </td>
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
                        <td className="readout pl-3">
                            <Cost usd={outside.cost_usd ?? null} />
                        </td>
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
                            <td className="readout pl-3">
                                <Cost usd={m.cost_usd ?? null} />
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
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
                            <td className="readout pl-3">
                                <Cost usd={t.cost_usd ?? null} />
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}
