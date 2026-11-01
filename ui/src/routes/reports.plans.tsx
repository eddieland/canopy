import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { plansReportQuery } from '@/api/queries'
import type { PlansGroup, PlansLength, PlansReport, PlansRow } from '@/api/types'
import { Age } from '@/components/age'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll, PanelSkeleton } from '@/components/panel'
import { RunLink } from '@/components/run-link'
import { Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Hinted, Tipped } from '@/components/tip'
import { WindowToggle } from '@/components/window-toggle'
import { counted } from '@/lib/descriptions'
import { grouped } from '@/lib/fold'
import {
    changesText,
    DEFAULT_PLANS_WINDOW,
    LEVEL_HINT,
    LIMITS_TEXT,
    measuredText,
    notProseText,
    lengthLinesText,
    lengthText,
    levelText,
    OUTCOME_HINT,
    OUTCOME_WORD,
    pagesText,
    PLANS_WINDOWS,
    plansLine,
    plansWindow,
    reasonsText,
    resumedText,
} from '@/lib/plan-report'
import { windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { hoursText } from '@/lib/reports'
import { cn } from '@/lib/utils'

interface PlansSearch {
    days?: number | undefined
}

// What the page shows on every visit, on its title's hover: its description is the window's state.
const HELP = [
    'How your plans were approved, split by the level of policy.planner_may_approve their planners were offered:',
    'by the planner, by you as written, or after a change, with how long approving took against how long the plan',
    "was, and whether the PR that followed needed a resume. A quick approval says little about a plan; its PR's",
    'resumes say more. Read it before loosening the key.',
].join(' ')

// What the needed-a-resume column counts, on its hover.
const RESUMED_HINT = 'Of the plans an implement followed, those whose PR needed at least one resume'

// What a length column measures, ending its hover: a page is the server's `page_lines`.
const PAGE_HINT = 'in pages of the plan editor, about a screen each, as its planner wrote it'

// What a plan whose file as its planner wrote it could not be read shows, on its dash's hover.
const UNMEASURED = 'Its file as its planner wrote it could not be read'

// The column names of a table in a padded scrolling region: the head's cells take the padding.
const PADDED_HEAD = 'sticky top-0 bg-surface [&_th]:pt-3'

/**
 * How the last days' plans were approved, by the level their planners were offered, and what their PRs needed after:
 * each level's approvals by outcome, the time to approve by the plan's length, and each plan. The window is `?days=`,
 * 30 or 90 days; 30, the default, needs no search.
 */
export const Route = createFileRoute('/reports/plans')({
    // Typed search params: a window the page does not offer is dropped, which reads as 30 days.
    validateSearch: (search: Record<string, unknown>): PlansSearch => ({ days: plansWindow(search)?.days }),
    component: PlansPage,
})

function PlansPage() {
    const search = Route.useSearch()
    const shown: ReportWindow = search.days === undefined ? DEFAULT_PLANS_WINDOW : { days: search.days }
    const navigate = Route.useNavigate()
    const query = useQuery(plansReportQuery(shown.days ?? 30))
    const span = windowName(shown)
    const { data } = query
    // A read that failed with nothing on screen says so once, in the first panel, with Read again.
    const failed = data === undefined && query.error !== null
    return (
        <>
            <PageHeader
                title="Plans"
                help={HELP}
                controls={
                    <WindowToggle
                        windows={PLANS_WINDOWS}
                        shown={shown}
                        testId="plans"
                        onPick={(picked) => {
                            void navigate({
                                search: { days: picked === DEFAULT_PLANS_WINDOW ? undefined : picked.days },
                            })
                        }}
                    />
                }
            >
                {data === undefined ? (query.isPending ? 'reading the plans' : null) : plansLine(data)}
            </PageHeader>
            <Panel data-testid="plans-levels">
                <PanelHeader label="Approvals by level" />
                {data === undefined ? (
                    <PanelLoading query={query} className="min-h-48" />
                ) : (
                    <Levels found={data} span={span} />
                )}
            </Panel>
            {!failed && (
                <>
                    <Panel data-testid="plans-lengths">
                        <PanelHeader label="Time to approve by length" />
                        {data === undefined ? (
                            <PanelSkeleton rows={3} className="min-h-24" />
                        ) : (
                            <Lengths lengths={data.lengths} pageLines={data.page_lines} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="plans-plans">
                        <PanelHeader label="Each plan" />
                        {data === undefined ? (
                            <PanelSkeleton rows={4} className="min-h-32" />
                        ) : (
                            <Plans plans={data.plans} pageLines={data.page_lines} span={span} />
                        )}
                    </Panel>
                </>
            )}
        </>
    )
}

/**
 * The window's approved plans by the level their planners were offered and how each went ahead, with how long the
 * approval took, how long the plan was, and how many of the PRs that followed needed a resume. Then the key's level
 * now, and what the page cannot see.
 */
function Levels({ found, span }: { found: PlansReport; span: string }) {
    return (
        <div className="flex flex-col gap-3 p-3">
            {found.groups.length === 0 ? (
                <Empty size="panel">no plan was approved in these {span}</Empty>
            ) : (
                <PanelScroll label="Approvals by level" className="overflow-x-auto">
                    <table className="w-full border-collapse text-sm" data-testid="plans-group-table">
                        <thead>
                            <tr className="text-right">
                                <th className="panel-label pb-1.5 text-left font-normal">level</th>
                                <th className="panel-label pb-1.5 pl-3 text-left font-normal">approved</th>
                                <th className="panel-label pb-1.5 pl-3 font-normal">plans</th>
                                <th className="panel-label pb-1.5 pl-3 font-normal">
                                    <Hinted hint="From when each was written to its approval, the median">
                                        to approve
                                    </Hinted>
                                </th>
                                <th className="panel-label pb-1.5 pl-3 font-normal">
                                    <Hinted hint={`The median of their lengths, ${PAGE_HINT}`}>length</Hinted>
                                </th>
                                <th className="panel-label pb-1.5 pl-3 font-normal">
                                    <Hinted hint="The median of their words, outside code and diagrams">words</Hinted>
                                </th>
                                <th className="panel-label pb-1.5 pl-3 font-normal">
                                    <Hinted hint={RESUMED_HINT}>needed a resume</Hinted>
                                </th>
                                <th className="panel-label pb-1.5 pl-3 font-normal">
                                    <Hinted hint="Every resume after them">resumes</Hinted>
                                </th>
                                <th className="panel-label pb-1.5 pl-3 font-normal">
                                    <Hinted hint="Those whose ticket is done, so their resumes are all in">done</Hinted>
                                </th>
                            </tr>
                        </thead>
                        <tbody className="text-xs">
                            {found.groups.map((g) => (
                                <Group key={`${g.level ?? ''}:${g.outcome}`} group={g} pageLines={found.page_lines} />
                            ))}
                        </tbody>
                    </table>
                </PanelScroll>
            )}
            <p className="text-sm" data-testid="plans-key">
                <span className="text-muted-foreground">policy.planner_may_approve is</span>{' '}
                <Word word={found.level} meaning={LEVEL_HINT[found.level]} />{' '}
                <span className="text-muted-foreground">
                    now. {counted(found.outcomes.replaced ?? 0, 'plan')} sent back, {found.outcomes.waiting ?? 0}{' '}
                    waiting on you.
                </span>
            </p>
            <p className="text-xs text-muted-foreground" data-testid="plans-limits">
                {LIMITS_TEXT}
            </p>
        </div>
    )
}

/** One level's plans that went ahead one way: how many, how quickly, how long, and what their PRs needed after. */
function Group({ group, pageLines }: { group: PlansGroup; pageLines: number }) {
    return (
        <tr className="text-right" data-testid="plans-group">
            <th scope="row" className="py-0.5 text-left font-mono font-normal">
                <Hinted hint={LEVEL_HINT[group.level ?? '']}>{levelText(group.level)}</Hinted>
            </th>
            <td className="pl-3 text-left text-muted-foreground">
                <Hinted hint={OUTCOME_HINT[group.outcome]}>{OUTCOME_WORD[group.outcome]}</Hinted>
            </td>
            <td className="readout pl-3">{group.plans}</td>
            <td className="readout pl-3">
                {group.outcome === 'planner' ? '–' : hoursText(group.median_hours_to_approve)}
            </td>
            <td className="readout pl-3 whitespace-nowrap text-muted-foreground">
                {group.median_lines === null ? (
                    '–'
                ) : (
                    <Tipped fact={counted(group.median_lines, 'line')} mono>
                        {pagesText(group.median_lines, pageLines)}
                    </Tipped>
                )}
            </td>
            <td className="readout pl-3 text-muted-foreground">
                {group.median_words === null ? '–' : grouped(group.median_words)}
            </td>
            <td className={cn('readout pl-3', group.with_resume > 0 && 'text-status-blocked')}>{resumedText(group)}</td>
            <td className="readout pl-3 text-muted-foreground">{group.resumes}</td>
            <td className="readout pl-3 text-muted-foreground">{group.done}</td>
        </tr>
    )
}

/**
 * The plans you approved, by length: how many, the median time to approve them, and how many went as written. The
 * planner's approvals take no time, so they are left out.
 */
function Lengths({ lengths, pageLines, span }: { lengths: PlansLength[]; pageLines: number; span: string }) {
    if (lengths.length === 0) {
        return <Empty size="panel">you approved no plan in these {span}</Empty>
    }
    return (
        <div className="px-3 pb-3">
            <table className="w-full border-collapse text-sm" data-testid="plans-length-table">
                <thead>
                    <tr className="text-right [&_th]:pt-3">
                        <th className="panel-label pb-1.5 text-left font-normal">
                            <Hinted hint={`Their lengths, ${PAGE_HINT}`}>length</Hinted>
                        </th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">plans</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">median to approve</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">as written</th>
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {lengths.map((n) => (
                        <tr key={n.low} className="text-right" data-testid="plans-length">
                            <th scope="row" className="py-0.5 text-left font-normal">
                                <Tipped fact={lengthLinesText(n)} mono>
                                    {lengthText(n, pageLines)}
                                </Tipped>
                            </th>
                            <td className="readout pl-3">{n.plans}</td>
                            <td className="readout pl-3">{hoursText(n.median_hours_to_approve)}</td>
                            <td className="readout pl-3 text-muted-foreground">{n.as_written}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

/** Each plan written in the window, the newest first. */
function Plans({ plans, pageLines, span }: { plans: PlansRow[]; pageLines: number; span: string }) {
    if (plans.length === 0) {
        return <Empty size="panel">no plan was written in these {span}</Empty>
    }
    return (
        <PanelScroll label="Each plan" className="max-h-96 overflow-x-auto px-3 pb-3">
            <table className="w-full border-collapse text-sm" data-testid="plans-plan-table">
                <thead className={PADDED_HEAD}>
                    {/* The "how it went" column takes the slack, so each figure and its head keep to one line. */}
                    <tr className="text-left whitespace-nowrap">
                        <th className="panel-label pb-1.5 font-normal">plan</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">ticket</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">level</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">how it went</th>
                        <th className="panel-label pb-1.5 pl-3 text-right font-normal">
                            <Hinted hint={`Its length, ${PAGE_HINT}`}>length</Hinted>
                        </th>
                        <th className="panel-label pb-1.5 pl-3 text-right font-normal">
                            <Hinted hint="Its words, outside code and diagrams">words</Hinted>
                        </th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">
                            <Hinted hint="Its code blocks, tables, and diagrams">not prose</Hinted>
                        </th>
                        <th className="panel-label pb-1.5 pl-3 text-right font-normal">to approve</th>
                        <th className="panel-label pb-1.5 pl-3 text-right font-normal">resumes</th>
                        <th className="panel-label pb-1.5 pl-3 text-right font-normal">written</th>
                    </tr>
                </thead>
                <tbody className="text-xs">
                    {plans.map((p) => (
                        <Plan key={p.plan_id} plan={p} pageLines={pageLines} />
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}

/**
 * A plan's row: its run, its ticket, the level it was offered, how it went and what changed first, its length, words,
 * and what is not prose, how long approving it took, and the resumes its ticket needed after, with their reasons on
 * hover.
 */
function Plan({ plan, pageLines }: { plan: PlansRow; pageLines: number }) {
    const { metrics } = plan
    const changes = changesText(plan)
    const reasons = reasonsText(plan.reasons)
    return (
        <tr className="align-top" data-testid={`plans-plan-${plan.plan_id}`}>
            <th scope="row" className="py-0.5 text-left font-normal whitespace-nowrap">
                <RunLink id={plan.run_id} />
            </th>
            <td className="pl-3 whitespace-nowrap">
                <TicketLink ticketKey={plan.ticket_key} />
            </td>
            <td className="pl-3 font-mono whitespace-nowrap text-muted-foreground">
                <Hinted hint={LEVEL_HINT[plan.level ?? '']}>{levelText(plan.level)}</Hinted>
            </td>
            <td className="w-full pl-3 text-muted-foreground">
                <Hinted hint={OUTCOME_HINT[plan.outcome]}>{OUTCOME_WORD[plan.outcome]}</Hinted>
                {changes !== '' && <span>: {changes}</span>}
            </td>
            <td className="readout pl-3 text-right whitespace-nowrap text-muted-foreground">
                <Tipped fact={metrics ? measuredText(metrics, plan.size) : UNMEASURED} mono={Boolean(metrics)}>
                    {metrics ? pagesText(metrics.lines, pageLines) : '–'}
                </Tipped>
            </td>
            <td className="readout pl-3 text-right whitespace-nowrap text-muted-foreground">
                {metrics ? grouped(metrics.words) : '–'}
            </td>
            <td className="pl-3 whitespace-nowrap text-muted-foreground">
                {metrics ? notProseText(metrics) || '–' : '–'}
            </td>
            <td className="readout pl-3 text-right whitespace-nowrap">
                {plan.outcome === 'planner' ? '–' : hoursText(plan.hours_to_approve)}
            </td>
            <td className={cn('readout pl-3 text-right whitespace-nowrap', plan.resumes > 0 && 'text-status-blocked')}>
                <Tipped fact={plan.implemented ? reasons : 'No implement followed it'}>
                    {plan.implemented ? plan.resumes : '–'}
                </Tipped>
            </td>
            <td className="pl-3 text-right whitespace-nowrap">
                <Age at={plan.created_at} variant="ago" />
            </td>
        </tr>
    )
}
