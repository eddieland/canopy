import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { BookOpen, SlidersHorizontal } from 'lucide-react'
import type { ReactNode } from 'react'

import { choresQuery, metaQuery, reviewsQuery, runsQuery, spendQuery, tasksQuery } from '@/api/queries'
import type { Run, RunState, Spend, SpendWindow } from '@/api/types'
import { Age } from '@/components/age'
import { Cost } from '@/components/cost'
import { RunDot } from '@/components/status'
import { TicketTitle } from '@/components/ticket-title'
import { Skeleton } from '@/components/ui/skeleton'
import { ProgressMeter } from '@/components/run-progress'
import { useLoopDown } from '@/hooks/use-loop-down'
import { useClock } from '@/lib/clock'
import type { Clock } from '@/lib/clock'
import { pullRequestLabel } from '@/lib/pull-request-label'
import { choreRunRef, reviewRef, runRef, taskRunRef } from '@/lib/refs'
import { runPhase, useQuips } from '@/lib/run-phase'
import { railWork } from '@/lib/run-state'
import type { RailItem } from '@/lib/run-state'
import { taskTitle } from '@/lib/tasks'
import { stamp } from '@/lib/time'
import { cn } from '@/lib/utils'

// Where the version links: every release's notes, newest first.
const RELEASES = 'https://github.com/eddieland/canopy/releases'

// Rows the rail lists before `+N more`: with the nav and the spend, four keep the sticky part within an 800px window.
const RAIL_ROWS = 4

// What `+N more` says on hover, by the page it opens.
const MORE_TITLE = {
    '/runs': 'Every run, on the runs page',
    '/pull-requests/reviews': 'Every review, on the reviews page',
    '/chores': 'Every chore, on the chores page',
    '/tasks': 'Every task, on the tasks page',
} as const

/**
 * Under the nav, on every page: what is working now, each row opening its page. The worker runs, the reviews of PRs,
 * the chore runs, and the task runs running come first, then the worker runs waiting on the operator's answer. All
 * four come whole from the stream, so a row appears when its run starts and leaves when it ends.
 */
export function RailWorking() {
    const runs = useQuery(runsQuery).data
    const reviews = useQuery(reviewsQuery).data
    const chores = useQuery(choresQuery).data
    const tasks = useQuery(tasksQuery).data
    const { shown, more, moreAt } = railWork({ runs: runs ?? [], reviews, chores, tasks }, RAIL_ROWS)
    // While the loop isn't answering, these are only what it last said: dimmed, as stale search hits are.
    const stale = useLoopDown().offline
    return (
        <RailSection
            label="Working"
            testId="rail-working"
            count={runs === undefined ? undefined : shown.length + more}
            stale={stale}
        >
            {runs === undefined ? (
                <Skeleton className="mx-2.5 h-8" />
            ) : shown.length === 0 ? (
                <p className="px-2.5 text-xs text-muted-foreground">nothing working now</p>
            ) : (
                <ul className="flex flex-col gap-0.5">
                    {shown.map((item) => (
                        <li key={itemKey(item)}>
                            <WorkingRow item={item} />
                        </li>
                    ))}
                    {more > 0 && (
                        <li>
                            <Link
                                to={moreAt}
                                title={MORE_TITLE[moreAt]}
                                className="block px-2.5 py-1 font-mono text-xs text-accent hover:underline"
                            >
                                +{more} more
                            </Link>
                        </li>
                    )}
                </ul>
            )}
        </RailSection>
    )
}

// Unique across the four kinds, whose ids are each their own table's.
function itemKey(item: RailItem): string {
    switch (item.kind) {
        case 'run': {
            return `run-${item.run.id}`
        }
        case 'review': {
            return `review-${item.review.id}`
        }
        case 'chore': {
            return `chore-${item.chore}-${item.run.id}`
        }
        case 'task': {
            return `task-${item.task.id}-${item.run.id}`
        }
    }
}

/**
 * One row of what is working, opening its page: a dot in its state's color, what it works on (a ticket's key, a PR, a
 * chore, a task's run), how long it has run or `waiting on you`, and under it what it is: the ticket's title, the
 * review, the run, the task's first line. A worker run adds what it is doing, `planning`, on a line of its own, and
 * while it runs, its steps' meter when its progress names any; a
 * task's run has no kind or reasons to name a phase by, and its first line is the operator's own words.
 */
function WorkingRow({ item }: { item: RailItem }) {
    switch (item.kind) {
        case 'run': {
            const { run } = item
            return (
                <Link
                    to="/runs/$id"
                    params={{ id: String(run.id) }}
                    title={`${runRef(run.id)} ${run.kind}`}
                    className={ROW}
                    data-testid={`rail-run-${run.id}`}
                >
                    <RowHead state={run.state} subject={run.ticket_key} started={run.started_at} />
                    <TicketTitle title={run.ticket_title} className="pl-4 text-xs font-normal text-muted-foreground" />
                    <PhaseLine run={run} />
                    {run.state === 'running' && run.card !== null && run.card.steps.length > 0 && (
                        <ProgressMeter card={run.card} className="mt-0.5 ml-4" />
                    )}
                </Link>
            )
        }
        case 'review': {
            const { review } = item
            const pr = pullRequestLabel(review.pr_url)
            return (
                <Link
                    to="/pull-requests/reviews/$id"
                    params={{ id: String(review.id) }}
                    title={`${reviewRef(review.id)} of ${pr}`}
                    className={ROW}
                    data-testid={`rail-review-${review.id}`}
                >
                    <RowHead state={review.state} subject={pr} started={review.started_at} />
                    <Under>
                        {review.ticket_key === null
                            ? reviewRef(review.id)
                            : `${reviewRef(review.id)} · ${review.ticket_key}`}
                    </Under>
                </Link>
            )
        }
        case 'chore': {
            const { chore, run } = item
            return (
                <Link
                    to="/chores/$name/runs/$id"
                    params={{ name: chore, id: String(run.id) }}
                    title={choreRunRef(chore, run.id)}
                    className={ROW}
                    data-testid={`rail-chore-${chore}`}
                >
                    <RowHead state={run.state} subject={chore} started={run.started_at} />
                    <Under>{`chore run #${run.id}`}</Under>
                </Link>
            )
        }
        case 'task': {
            const { task, run } = item
            return (
                <Link
                    to="/tasks/$id/runs/$run"
                    params={{ id: String(task.id), run: String(run.id) }}
                    title={taskRunRef(task.id, run.id)}
                    className={ROW}
                    data-testid={`rail-task-${task.id}`}
                >
                    <RowHead state={run.state} subject={taskRunRef(task.id, run.id)} started={run.started_at} />
                    <TicketTitle
                        title={taskTitle(task.text)}
                        className="pl-4 text-xs font-normal text-muted-foreground"
                    />
                </Link>
            )
        }
    }
}

// A working row's link: its head line over what goes under it.
const ROW = 'flex flex-col gap-0.5 rounded-sm px-2.5 py-1.5 hover:bg-surface-raised'

/** A working row's head line: its dot, what it works on, and how long it has run, or `waiting on you`. */
function RowHead({ state, subject, started }: { state: RunState; subject: string; started: string }) {
    return (
        <span className="flex items-center gap-2 font-mono text-xs">
            <RunDot state={state} />
            <span className="min-w-0 truncate text-foreground">{subject}</span>
            <span className="ml-auto shrink-0">
                {state === 'blocked' ? (
                    <span className="font-sans whitespace-nowrap text-status-blocked">waiting on you</span>
                ) : (
                    <Age at={started} />
                )}
            </span>
        </span>
    )
}

/**
 * Under a worker run's ticket title: what it is doing in plain words, `planning`, or while it works and Settings leaves
 * them on, its quip for this ticket and phase, `planning in pencil`, with the plain words on hover.
 */
function PhaseLine({ run }: { run: Run }) {
    const { word, quip } = runPhase(run)
    const quipped = useQuips() === 'on' && run.state === 'running' && quip !== null
    return (
        <span
            title={quipped ? word : undefined}
            className={cn(
                'min-w-0 truncate pl-4 text-xs text-muted-foreground',
                quipped ? 'font-sans italic' : 'font-mono',
            )}
            data-testid={`rail-phase-${run.id}`}
        >
            {quipped ? quip : word}
        </span>
    )
}

/** The line under a review's or a chore run's head line, where a worker run's ticket title and a task's text go. */
function Under({ children }: { children: string }) {
    return <span className="min-w-0 truncate pl-4 font-mono text-xs text-muted-foreground">{children}</span>
}

/**
 * Under what is working, in two rows: what the last 24 hours and then the last 30 days cost, each window's name on the
 * left, standing for the block's label, and its cost on the right, so the figures line up however many digits they
 * have. The 30 days, the figure the operator watches, is the larger. Either opens the spend page over its own window:
 * the 24 hours by the hour, or the 30 days by the day.
 */
export function RailSpend() {
    const spend = useQuery(spendQuery).data
    const clock = useClock()
    const outside = outsideHint(spend, clock)
    return (
        <section aria-label="Spent" className={SECTION} data-testid="rail-spend">
            <div className="grid gap-y-0.5 px-2.5">
                <Spent
                    window={spend?.day}
                    label="24h"
                    hint={`Spent in the last 24 hours${outside}: the day by hour`}
                    hours={24}
                />
                <Spent
                    window={spend?.month}
                    label="30d"
                    hint={`Spent in the last 30 days${outside}: the month by day`}
                    days={30}
                    headline
                />
            </div>
        </section>
    )
}

/**
 * The rail's foot, on two lines: the version canopy serves, with the width to itself, cut short only past a long
 * build's hash, opening the releases on GitHub in a new tab; and under it two buttons alike, the guide, the operator's
 * documentation, bundled with that version, and Settings, which the operator opens too seldom to take a place in the
 * nav. Always at the window's foot, however long the page.
 */
export function RailFooter() {
    const meta = useQuery(metaQuery).data
    return (
        // pb-2: a little room under the buttons, so they do not sit on the window's edge.
        <div
            className="mx-2 flex flex-col gap-1 border-t px-2.5 pt-1 pb-2 text-xs text-muted-foreground"
            data-testid="rail-footer"
        >
            <a
                href={RELEASES}
                target="_blank"
                rel="noreferrer noopener"
                title={meta === undefined ? undefined : `canopy ${meta.version}: the releases on GitHub`}
                className="readout min-h-4 min-w-0 truncate rounded-sm text-foreground/80 hover:text-foreground"
                data-testid="rail-version"
            >
                {meta === undefined ? '' : `canopy ${meta.version}`}
            </a>
            <div className="flex items-center gap-1.5">
                <FooterLink to="/guide" title="How the web UI works, a page each" testId="rail-guide">
                    <BookOpen aria-hidden />
                    Guide
                </FooterLink>
                <FooterLink
                    to="/settings"
                    title="The theme, the send key, the fun, and the session"
                    testId="rail-settings"
                >
                    <SlidersHorizontal aria-hidden />
                    Settings
                </FooterLink>
            </div>
        </div>
    )
}

/** A page the rail's foot opens, as a filled pill in `foreground` so it stands out from the version's print. */
function FooterLink({
    to,
    title,
    testId,
    children,
}: {
    to: '/guide' | '/settings'
    title: string
    testId: string
    children: ReactNode
}) {
    return (
        <Link
            to={to}
            title={title}
            data-testid={testId}
            className={cn(
                'flex h-7 items-center gap-1.5 rounded-md bg-surface-raised px-2.5 text-sm text-foreground',
                'transition-colors outline-none hover:bg-surface focus-visible:ring-2 focus-visible:ring-ring',
                '[&_svg]:size-3.5',
            )}
        >
            {children}
        </Link>
    )
}

// A block of the rail's room: a hairline above, and the space either side of it.
const SECTION = 'mx-2 mt-3 border-t pt-3'

/** A block of the rail: a hairline above, a label, and what it holds. */
function RailSection({
    label,
    testId,
    count,
    stale = false,
    children,
}: {
    label: string
    testId: string
    count?: number
    stale?: boolean
    children: ReactNode
}) {
    return (
        <section
            aria-label={label}
            className={cn(SECTION, 'transition-opacity', stale && 'opacity-60')}
            data-stale={stale || undefined}
            data-testid={testId}
        >
            <div className="flex items-center justify-between px-2.5 pb-1.5">
                <span className="panel-label">{label}</span>
                {count !== undefined && <span className="readout text-2xs text-muted-foreground">{count}</span>}
            </div>
            {children}
        </section>
    )
}

/**
 * What the counters count besides canopy's runs, for their hover: the runtime's sessions outside canopy, as of when
 * `canopy loop` last read them, or that it has not yet. Empty before the spend arrives.
 */
function outsideHint(spend: Spend | undefined, clock: Clock): string {
    if (spend === undefined) {
        return ''
    }
    return spend.sessions_read_at === null
        ? ", canopy's runs alone until canopy loop reads the sessions outside canopy"
        : `, canopy's runs and the sessions outside canopy as of ${stamp(spend.sessions_read_at, clock)}`
}

/**
 * One window's row: its name on the left and its cost on the right, a dash when nothing in it reported one, opening the
 * spend page over `hours` or `days`. A `headline` cost is a step larger. The row keeps its height before the cost
 * arrives.
 */
function Spent({
    window,
    label,
    hint,
    hours,
    days,
    headline = false,
}: {
    window: SpendWindow | undefined
    label: string
    hint: string
    hours?: 24
    days?: 30
    headline?: boolean
}) {
    const cost = window?.cost_usd ?? null
    return (
        <Link
            to="/reports/spend"
            search={{ days, hours }}
            className={cn(
                '-mx-1 flex items-baseline justify-between gap-3 rounded-sm px-1 hover:bg-surface-raised',
                headline ? 'min-h-5' : 'min-h-4',
            )}
            title={hint}
            data-testid={`rail-spend-link-${label}`}
        >
            <span className="panel-label">{label}</span>
            {window === undefined ? (
                <Skeleton className="h-4 w-14 self-center" />
            ) : (
                <span
                    className={cn('readout text-right text-foreground', headline ? 'text-sm font-medium' : 'text-xs')}
                    data-testid={`rail-spend-${label}`}
                >
                    <Cost usd={cost} />
                </span>
            )}
        </Link>
    )
}
