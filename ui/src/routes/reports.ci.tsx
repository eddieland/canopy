import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { ciReportQuery } from '@/api/queries'
import type { CiCheck, CiDay, CiFix, CiFixedCheck, CiKick, CiKickedPullRequest, CiReport } from '@/api/types'
import { Age } from '@/components/age'
import { CellBar } from '@/components/cell-bar'
import { ChartTable } from '@/components/chart-table'
import { Cost } from '@/components/cost'
import { DayChart, DayChartLegend } from '@/components/day-chart'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll, PanelSkeleton } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { PullRequestTable } from '@/components/pull-request-table'
import type { PullRequestColumn } from '@/components/pull-request-table'
import { ReadoutTiles } from '@/components/readout-tiles'
import type { ReadoutTile } from '@/components/readout-tiles'
import { RunLink } from '@/components/run-link'
import { Word } from '@/components/status'
import { TickLink } from '@/components/tick-link'
import { TicketLink } from '@/components/ticket-link'
import { Clipped, Hinted } from '@/components/tip'
import { WindowToggle } from '@/components/window-toggle'
import { barPercent } from '@/lib/chart'
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
    kickText,
    LIMITS_TEXT,
    nextHeadText,
    nextText,
    previousCiFigures,
    redSum,
    VERDICTS_TEXT,
} from '@/lib/ci'
import { useClock } from '@/lib/clock'
import { counted } from '@/lib/descriptions'
import { pointsChange, readoutDelta, wholeChange } from '@/lib/readout-delta'
import { windowBefore, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { dayName, shareText } from '@/lib/spend'
import { cn } from '@/lib/utils'

interface CiSearch {
    days?: number | undefined
}

// What the page shows on every visit, on its title's hover: its description is the window's state.
const HELP = [
    'What CI did on the PRs canopy observed: each check by how often it went red and how often the next head fixed',
    'it, the red checks by day, the resumes that fixed CI and what they cost, the flaky kicks, and the cooldown.',
    LIMITS_TEXT,
].join(' ')

// What a column counts, in its name's tip.
const RATE_HINT = "Its red runs' share of its red and green ones"
const NEXT_HEAD_HINT = 'Of its red runs a run on a new head of the same PR followed, how many passed'
const FIXED_HINT = "The checks red on its PR's head when it started, and how each ran on the next head"

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
                    <Panel data-testid="ci-kicks">
                        <PanelHeader label="Flaky kicks">
                            <span className="readout text-xs text-muted-foreground" data-testid="ci-kick-limit">
                                {data === undefined ? '' : `trust.max_flaky_kicks = ${data.max_flaky_kicks}`}
                            </span>
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton rows={3} className="min-h-24" />
                        ) : (
                            <Kicks found={data} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="ci-cooldown">
                        <PanelHeader label="Cooldown refusals" />
                        {data === undefined ? (
                            <PanelSkeleton rows={1} className="min-h-12" />
                        ) : (
                            <Cooldown found={data} span={span} />
                        )}
                    </Panel>
                </>
            )}
        </>
    )
}

/**
 * The window's headline figures, each held in its place while the report is read, and each against the window
 * before's: more heads green first time, and fewer red runs, are better.
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
    ]
}

/**
 * Each check by name, the worst first: its runs, its red runs, its share of red among red and green, and how often
 * its next run on a new head passed after a red one. Under it, what counts as red, and what the page cannot see.
 */
function Checks({ checks, span }: { checks: CiCheck[]; span: string }) {
    return (
        <div className="flex flex-col gap-3 p-3">
            {checks.length === 0 ? (
                <Empty size="panel">no check run was observed in these {span}</Empty>
            ) : (
                <PanelScroll label="Checks by name" className="max-h-96 overflow-x-auto">
                    <table className="w-full border-collapse text-sm" data-testid="ci-check-table">
                        <thead className="sticky top-0 bg-surface">
                            <tr className="text-right">
                                <th className="panel-label pb-1.5 text-left font-normal">check</th>
                                <th className="panel-label pb-1.5 pl-3 font-normal">runs</th>
                                <th className="panel-label pb-1.5 pl-3 font-normal">red</th>
                                <th className="panel-label pb-1.5 pl-3 text-left font-normal">
                                    <Hinted hint={RATE_HINT}>failure rate</Hinted>
                                </th>
                                <th className="panel-label pb-1.5 pl-3 font-normal">
                                    <Hinted hint={NEXT_HEAD_HINT}>next head green</Hinted>
                                </th>
                            </tr>
                        </thead>
                        <tbody className="font-mono text-xs">
                            {checks.map((c) => (
                                <tr key={c.name} className="text-right" data-testid="ci-check">
                                    <th scope="row" className="max-w-0 py-0.5 text-left font-normal">
                                        <Clipped text={c.name} className="block" />
                                    </th>
                                    <td className="readout pl-3 text-muted-foreground">{c.runs}</td>
                                    <td className={cn('readout pl-3', c.red > 0 && 'text-status-failed')}>{c.red}</td>
                                    <td className="pl-3">
                                        <CellBar
                                            percent={barPercent(
                                                failureShare(c),
                                                checks.map((check) => failureShare(check)),
                                            )}
                                            valueClassName="readout w-10 text-right"
                                        >
                                            {failureRate(c)}
                                        </CellBar>
                                    </td>
                                    <td className="readout pl-3 text-muted-foreground">{nextHeadText(c)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </PanelScroll>
            )}
            <p className="text-xs text-muted-foreground" data-testid="ci-limits">
                {VERDICTS_TEXT} {LIMITS_TEXT}
            </p>
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
                <table className="w-full border-collapse text-sm" data-testid="ci-table">
                    <thead className="sticky top-0 bg-surface">
                        <tr className="text-right">
                            <th className="panel-label pb-1.5 text-left font-normal">day</th>
                            {series.map((s) => (
                                <th key={s.key} className="panel-label pb-1.5 pl-3 font-normal">
                                    {s.label}
                                </th>
                            ))}
                            <th className="panel-label pb-1.5 pl-3 font-normal">red</th>
                        </tr>
                    </thead>
                    <tbody className="font-mono text-xs">
                        {found.per_day.toReversed().map((day: CiDay) => (
                            <tr key={day.day} className="text-right" data-testid={`ci-day-${day.day}`}>
                                <th scope="row" className="readout py-0.5 text-left font-normal">
                                    {dayName(day, clock)}
                                </th>
                                {series.map((s, i) => (
                                    <td key={s.key} className="readout pl-3 text-muted-foreground">
                                        {day.red[i] ?? 0}
                                    </td>
                                ))}
                                <td className={cn('readout pl-3', redSum(day) > 0 && 'text-status-failed')}>
                                    {redSum(day)}
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
 * Each `resume` for `ci` that started in the window, the newest first, a retired `fix-ci` among them: the run, its
 * ticket, how it ended, the checks red on its PR's head when it started with how each one's first run on the next
 * head ended, what it cost, and when it started.
 */
function Fixes({ fixes, span }: { fixes: CiFix[]; span: string }) {
    if (fixes.length === 0) {
        return <Empty size="panel">no resume for CI started in these {span}</Empty>
    }
    return (
        <PanelScroll label="Fix-CI resumes" className="max-h-96 overflow-x-auto px-3 pb-3">
            <table className="w-full border-collapse text-sm" data-testid="ci-fix-table">
                <thead className="sticky top-0 bg-surface [&_th]:pt-3">
                    <tr className="text-left">
                        <th className="panel-label pb-1.5 font-normal">run</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">ticket</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">ended</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">
                            <Hinted hint={FIXED_HINT}>checks, then the next head</Hinted>
                        </th>
                        <th className="panel-label pb-1.5 pl-3 text-right font-normal">spent</th>
                        <th className="panel-label pb-1.5 pl-3 text-right font-normal">started</th>
                    </tr>
                </thead>
                <tbody className="text-xs">
                    {fixes.map((f) => (
                        <tr key={f.run_id} className="align-top" data-testid={`ci-fix-${f.run_id}`}>
                            <th scope="row" className="py-0.5 text-left font-normal whitespace-nowrap">
                                <RunLink id={f.run_id} />
                                {f.kind !== 'resume' && (
                                    <Word word={f.kind} className="ml-2 font-mono text-muted-foreground" />
                                )}
                            </th>
                            <td className="pl-3 whitespace-nowrap">
                                <TicketLink ticketKey={f.ticket_key} />
                            </td>
                            <td className="pl-3 font-mono whitespace-nowrap text-muted-foreground">
                                <Word word={f.status} />
                            </td>
                            <td className="w-full pl-3">
                                <FixedChecks checks={f.checks} />
                            </td>
                            <td className="readout pl-3 text-right text-muted-foreground">
                                <Cost usd={f.cost_usd} />
                            </td>
                            <td className="pl-3 text-right whitespace-nowrap">
                                <Age at={f.started_at} variant="ago" />
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}

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

/**
 * The window's flaky kicks: by PR, against `trust.max_flaky_kicks`, then each kick whose check came back red. With
 * kicks off and none made, it says they are off, and where that is set.
 */
function Kicks({ found, span }: { found: CiReport; span: string }) {
    if (found.kicks.length === 0) {
        return found.max_flaky_kicks === 0 ? (
            <Empty size="panel">
                kicks are off: trust.max_flaky_kicks is 0, so a check a worker calls flaky waits for you to rerun it
            </Empty>
        ) : (
            <Empty size="panel">no flaky kick in these {span}</Empty>
        )
    }
    const red = found.kicks.filter((k) => k.still_red.length > 0)
    return (
        <div className="flex flex-col">
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

/** What the cooldown guard refused in the window, as the health page counts it, linking there rather than repeating. */
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
            <p className="p-3 text-sm text-muted-foreground" data-testid="ci-cooldown-line">
                The cooldown held no resume in these {span}. {health} has every guard&apos;s refusals.
            </p>
        )
    }
    const { decisions, ticks, last_tick: last } = found.cooldown
    return (
        <p className="p-3 text-sm" data-testid="ci-cooldown-line">
            The cooldown held {decisions === 1 ? '1 resume' : `${decisions} resumes`} in{' '}
            {ticks === 1 ? '1 tick' : `${ticks} ticks`}, the latest <TickLink id={last} />. {health} has every
            guard&apos;s refusals.
        </p>
    )
}
