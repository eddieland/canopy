import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { choresQuery, loopQuery, reviewsQuery, runsQuery, tasksQuery, ticksQuery, worktreesQuery } from '@/api/queries'
import { CapacityLine } from '@/components/capacity-line'
import { Notice } from '@/components/notice'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { PoolCounters } from '@/components/pool-counters'
import { SubjectRunsTable } from '@/components/runs-table'
import { TickNow } from '@/components/tick-now'
import { TickRow } from '@/components/tick-row'
import { busy, runningTasks, subjectRuns } from '@/lib/run-state'
import { Code } from '@/components/code'

// How many of the latest ticks the overview shows; the rest are on the ticks page.
const TICKS_SHOWN = 5

/**
 * What the loop does in the workspace, at a glance: the worktree pools, the runs working now, and the overseer's latest
 * ticks, each a summary of a page under Workspace (`/workspace/runs`, `/workspace/ticks`, `/workspace/worktrees`).
 */
export const Route = createFileRoute('/workspace/')({
    component: WorkspacePage,
})

function WorkspacePage() {
    const runsRead = useQuery(runsQuery)
    const runs = runsRead.data
    const reviews = useQuery(reviewsQuery).data
    const chores = useQuery(choresQuery).data
    const tasks = useQuery(tasksQuery).data
    const capacity = useQuery(loopQuery).data?.capacity
    const ticksRead = useQuery(ticksQuery)
    const ticks = ticksRead.data
    const pools = useQuery(worktreesQuery)
    // Every subject whose latest run is working now, as the runs page lists them under `?state=running`.
    const running =
        runs === undefined
            ? undefined
            : subjectRuns({ runs, reviews, chores, tasks }).filter((g) => g.latest.state === 'running')
    return (
        <>
            <PageHeader
                title="Workspace"
                links={
                    runs !== undefined &&
                    capacity !== undefined && (
                        <CapacityLine
                            capacity={capacity}
                            busy={busy({ runs, reviews, chores, tasks })}
                            tasks={runningTasks(tasks ?? []).length}
                        />
                    )
                }
            >
                What the loop does in this workspace, at a glance: the worktree pools, the runs working in them now, and
                the overseer&apos;s latest ticks, each on a page of its own under Workspace:{' '}
                <Under to="/workspace/runs">Runs</Under>, <Under to="/workspace/ticks">Ticks</Under>, and{' '}
                <Under to="/workspace/worktrees">Worktrees</Under>.
            </PageHeader>
            <PoolCounters pools={pools.data} />
            {/* The counters wait on the pools' read; one that failed says why under them, as on the worktrees page. */}
            <Notice error={pools.error} subject="worktrees" />
            <Panel>
                <PanelHeader label="Running now">
                    <span className="flex items-center gap-2">
                        <PanelLink to="/workspace/runs">All runs</PanelLink>
                        <span className="readout text-xs text-muted-foreground" data-testid="workspace-running-count">
                            {running?.length ?? ''}
                        </span>
                    </span>
                </PanelHeader>
                {running === undefined ? (
                    <PanelLoading query={runsRead} className="min-h-24" />
                ) : running.length === 0 ? (
                    <Empty>nothing runs now: the ones that ended are on Runs</Empty>
                ) : (
                    <SubjectRunsTable groups={running} />
                )}
            </Panel>
            <Panel>
                <PanelHeader label="Latest ticks">
                    <span className="flex items-center gap-2">
                        <PanelLink to="/workspace/ticks">All ticks</PanelLink>
                        <span className="readout text-xs text-muted-foreground" data-testid="workspace-ticks-count">
                            {ticks === undefined ? '' : Math.min(ticks.length, TICKS_SHOWN)}
                        </span>
                    </span>
                </PanelHeader>
                {ticks === undefined ? (
                    <PanelLoading query={ticksRead} className="min-h-40" />
                ) : ticks.length === 0 ? (
                    <Empty>
                        no ticks yet: the loop runs one every <Code>loop.interval_minutes</Code>, or now with{' '}
                        <TickNow inline />
                    </Empty>
                ) : (
                    <ul className="divide-y" data-testid="workspace-ticks">
                        {ticks.slice(0, TICKS_SHOWN).map((tick) => (
                            <TickRow key={tick.id} tick={tick} />
                        ))}
                    </ul>
                )}
            </Panel>
        </>
    )
}

/** A link in the description to a page under Workspace. */
function Under({ to, children }: { to: UnderWorkspace; children: ReactNode }) {
    return (
        <Link to={to} className="text-accent underline-offset-4 hover:underline">
            {children}
        </Link>
    )
}

/** A panel header's link to the page it summarizes. */
function PanelLink({ to, children }: { to: UnderWorkspace; children: ReactNode }) {
    return (
        <Link to={to} className="text-xs text-accent underline-offset-4 hover:underline">
            {children}
        </Link>
    )
}

/** A page under Workspace. */
type UnderWorkspace = '/workspace/runs' | '/workspace/ticks' | '/workspace/worktrees'
