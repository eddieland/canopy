import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { plansReportQuery } from '@/api/queries'
import type { PlansGroup, PlansLength, PlansReport, PlansRow } from '@/api/types'
import { Age } from '@/components/age'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelSkeleton } from '@/components/panel'
import { ReportTable } from '@/components/report-table'
import type { ReportColumn } from '@/components/report-table'
import { RunLink } from '@/components/run-link'
import { Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Clipped, Hinted, Tipped } from '@/components/tip'
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
        <div className="flex flex-col gap-3 px-3 pb-3">
            {found.groups.length === 0 ? (
                <Empty size="panel" className="mt-3">
                    no plan was approved in these {span}
                </Empty>
            ) : (
                <ReportTable
                    rows={found.groups}
                    columns={groupColumns(found.page_lines)}
                    rowKey={(g) => `${g.level ?? ''}:${g.outcome}`}
                    label="Approvals by level"
                    className="max-h-96"
                    testId="plans-group-table"
                    rowTestId="plans-group"
                />
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

/**
 * The approvals table's columns, a level's plans that went ahead one way: the level, how they went ahead, how many,
 * how quickly, how long, and what their PRs needed after.
 */
function groupColumns(pageLines: number): ReportColumn<PlansGroup>[] {
    return [
        {
            key: 'level',
            kind: 'name',
            label: 'level',
            cell: (g) => (
                <span className="font-mono">
                    <Hinted hint={LEVEL_HINT[g.level ?? '']}>{levelText(g.level)}</Hinted>
                </span>
            ),
        },
        {
            key: 'approved',
            kind: 'word',
            label: 'approved',
            cell: (g) => <Hinted hint={OUTCOME_HINT[g.outcome]}>{OUTCOME_WORD[g.outcome]}</Hinted>,
            muted: true,
        },
        { key: 'plans', kind: 'figure', label: 'plans', cell: (g) => g.plans },
        {
            key: 'to-approve',
            kind: 'figure',
            label: 'to approve',
            hint: 'From when each was written to its approval, the median',
            cell: (g) => (g.outcome === 'planner' ? '–' : hoursText(g.median_hours_to_approve)),
        },
        {
            key: 'length',
            kind: 'figure',
            label: 'length',
            hint: `The median of their lengths, ${PAGE_HINT}`,
            cell: (g) =>
                g.median_lines === null ? (
                    '–'
                ) : (
                    <Tipped fact={counted(g.median_lines, 'line')} mono>
                        {pagesText(g.median_lines, pageLines)}
                    </Tipped>
                ),
            muted: true,
        },
        {
            key: 'words',
            kind: 'figure',
            label: 'words',
            hint: 'The median of their words, outside code and diagrams',
            cell: (g) => (g.median_words === null ? '–' : grouped(g.median_words)),
            muted: true,
        },
        {
            key: 'resumed',
            kind: 'figure',
            label: 'needed a resume',
            hint: RESUMED_HINT,
            cell: resumedText,
            tone: (g) => g.with_resume > 0 && 'text-status-blocked',
        },
        {
            key: 'resumes',
            kind: 'figure',
            label: 'resumes',
            hint: 'Every resume after them',
            cell: (g) => g.resumes,
            muted: true,
        },
        {
            key: 'done',
            kind: 'figure',
            label: 'done',
            hint: 'Those whose ticket is done, so their resumes are all in',
            cell: (g) => g.done,
            muted: true,
        },
    ]
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
        <ReportTable
            rows={lengths}
            columns={lengthColumns(pageLines)}
            rowKey={(n) => String(n.low)}
            label="Time to approve by length"
            testId="plans-length-table"
            rowTestId="plans-length"
        />
    )
}

/** The lengths table's columns: the length, its plans, the median time to approve them, and how many as written. */
function lengthColumns(pageLines: number): ReportColumn<PlansLength>[] {
    return [
        {
            key: 'length',
            kind: 'name',
            label: 'length',
            hint: `Their lengths, ${PAGE_HINT}`,
            cell: (n) => (
                <span className="font-mono">
                    <Tipped fact={lengthLinesText(n)} mono>
                        {lengthText(n, pageLines)}
                    </Tipped>
                </span>
            ),
        },
        { key: 'plans', kind: 'figure', label: 'plans', cell: (n) => n.plans },
        {
            key: 'median',
            kind: 'figure',
            label: 'median to approve',
            cell: (n) => hoursText(n.median_hours_to_approve),
        },
        { key: 'as-written', kind: 'figure', label: 'as written', cell: (n) => n.as_written, muted: true },
    ]
}

/** Each plan written in the window, the newest first. */
function Plans({ plans, pageLines, span }: { plans: PlansRow[]; pageLines: number; span: string }) {
    if (plans.length === 0) {
        return <Empty size="panel">no plan was written in these {span}</Empty>
    }
    return (
        <ReportTable
            rows={plans}
            columns={planColumns(pageLines)}
            rowKey={(p) => String(p.plan_id)}
            label="Each plan"
            testId="plans-plan-table"
            rowTestId={(p) => `plans-plan-${p.plan_id}`}
        />
    )
}

/**
 * A plan's columns: its run, its ticket, the level it was offered, how it went and what changed first, its length,
 * words, and what is not prose, how long approving it took, and the resumes its ticket needed after, with their
 * reasons on hover, and when it was written.
 */
function planColumns(pageLines: number): ReportColumn<PlansRow>[] {
    return [
        { key: 'plan', kind: 'name', label: 'plan', cell: (p) => <RunLink id={p.run_id} /> },
        { key: 'ticket', kind: 'word', label: 'ticket', cell: (p) => <TicketLink ticketKey={p.ticket_key} /> },
        {
            key: 'level',
            kind: 'word',
            label: 'level',
            cell: (p) => (
                <span className="font-mono">
                    <Hinted hint={LEVEL_HINT[p.level ?? '']}>{levelText(p.level)}</Hinted>
                </span>
            ),
            muted: true,
        },
        { key: 'went', kind: 'free', label: 'how it went', cell: (p) => <HowItWent plan={p} />, muted: true },
        {
            key: 'length',
            kind: 'figure',
            label: 'length',
            hint: `Its length, ${PAGE_HINT}`,
            cell: ({ metrics, size }) => (
                <Tipped fact={metrics ? measuredText(metrics, size) : UNMEASURED} mono={Boolean(metrics)}>
                    {metrics ? pagesText(metrics.lines, pageLines) : '–'}
                </Tipped>
            ),
            muted: true,
        },
        {
            key: 'words',
            kind: 'figure',
            label: 'words',
            hint: 'Its words, outside code and diagrams',
            cell: ({ metrics }) => (metrics ? grouped(metrics.words) : '–'),
            muted: true,
        },
        {
            key: 'not-prose',
            kind: 'word',
            label: 'not prose',
            hint: 'Its code blocks, tables, and diagrams',
            cell: ({ metrics }) => (metrics ? notProseText(metrics) || '–' : '–'),
            muted: true,
        },
        {
            key: 'to-approve',
            kind: 'figure',
            label: 'to approve',
            cell: (p) => (p.outcome === 'planner' ? '–' : hoursText(p.hours_to_approve)),
        },
        {
            key: 'resumes',
            kind: 'figure',
            label: 'resumes',
            cell: (p) => (
                <Tipped fact={p.implemented ? reasonsText(p.reasons) : 'No implement followed it'}>
                    {p.implemented ? p.resumes : '–'}
                </Tipped>
            ),
            tone: (p) => p.resumes > 0 && 'text-status-blocked',
        },
        { key: 'written', kind: 'age', label: 'written', cell: (p) => <Age at={p.created_at} variant="ago" /> },
    ]
}

/** How a plan went ahead, and what changed first, cut to a line, whole on its hover while it is cut. */
function HowItWent({ plan }: { plan: PlansRow }) {
    const changes = changesText(plan)
    const word = OUTCOME_WORD[plan.outcome]
    return (
        <Clipped text={changes === '' ? word : `${word}: ${changes}`} className="block">
            <Hinted hint={OUTCOME_HINT[plan.outcome]}>{word}</Hinted>
            {changes !== '' && <span>: {changes}</span>}
        </Clipped>
    )
}
