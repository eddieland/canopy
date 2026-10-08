import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { ExternalLink, RotateCw } from 'lucide-react'

import { worktreesQuery } from '@/api/queries'
import { WORKTREE_STATES, type Pool, type Worktree, type WorktreeState } from '@/api/types'
import { Age } from '@/components/age'
import { Notice } from '@/components/notice'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { Chip } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { WORKTREE_DOT, WORKTREE_TEXT } from '@/lib/worktree-state'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/worktrees')({
    component: WorktreesPage,
})

function WorktreesPage() {
    const { data, error, isFetching, refetch } = useQuery(worktreesQuery)
    return (
        <>
            <PageHeader label="Pools" title="Worktrees">
                Every slot in canopy's treehouse pools: what holds it, what it has checked out, and what runs in it.
                Read from treehouse when the page opens and whenever a run starts or ends.
            </PageHeader>
            <div className="flex items-center justify-between gap-4">
                <Notice error={error} />
                <Button
                    variant="outline"
                    size="sm"
                    className="ml-auto"
                    onClick={() => void refetch()}
                    disabled={isFetching}
                    data-testid="worktrees-refresh"
                >
                    <RotateCw />
                    {isFetching ? 'Reading' : 'Read again'}
                </Button>
            </div>
            {data === undefined ? (
                <Panel>
                    <PanelHeader label="Loading" />
                    <div className="flex min-h-40 flex-col gap-2 p-3">
                        <Skeleton className="h-4 w-2/3" />
                        <Skeleton className="h-4 w-1/2" />
                    </div>
                </Panel>
            ) : (
                data.map((pool) => <PoolPanel key={pool.repo} pool={pool} />)
            )}
        </>
    )
}

function PoolPanel({ pool }: { pool: Pool }) {
    const counts = WORKTREE_STATES.map((s) => [s, pool.worktrees.filter((w) => w.state === s).length] as const)
    return (
        <Panel data-testid={`pool-${pool.repo}`}>
            <PanelHeader label={pool.repo}>
                <span className="flex items-center gap-3 font-mono text-xs text-muted-foreground">
                    {counts
                        .filter(([, n]) => n > 0)
                        .map(([state, n]) => (
                            <span key={state} className="flex items-center gap-1.5">
                                <WorktreeDot state={state} />
                                <span className="readout">{n}</span> {state}
                            </span>
                        ))}
                    {pool.size !== null && <span className="readout">size {pool.size}</span>}
                </span>
            </PanelHeader>
            {pool.error !== null ? (
                <Placeholder className="min-h-24">
                    <span className="text-status-failed">{pool.error}</span>
                </Placeholder>
            ) : pool.worktrees.length === 0 ? (
                <Placeholder className="min-h-24">no worktrees yet</Placeholder>
            ) : (
                <ul className="divide-y" data-testid="worktrees">
                    {pool.worktrees.map((w) => (
                        <WorktreeRow key={w.path} worktree={w} />
                    ))}
                </ul>
            )}
        </Panel>
    )
}

function WorktreeDot({ state }: { state: WorktreeState }) {
    return <span aria-hidden className={cn('inline-flex size-2 shrink-0 rounded-full', WORKTREE_DOT[state])} />
}

/** One slot: its state, name, what holds it, its branch, and for how long; then its path, processes, and any note. */
function WorktreeRow({ worktree: w }: { worktree: Worktree }) {
    const since = w.run?.started_at ?? w.review?.started_at ?? w.leased_at
    return (
        <li className="flex flex-col gap-1 px-3 py-2.5" data-testid={`worktree-${w.name}`} data-state={w.state}>
            <div className="flex h-5 items-center gap-3">
                <span className={cn('flex w-24 items-center gap-1.5 font-mono text-xs', WORKTREE_TEXT[w.state])}>
                    <WorktreeDot state={w.state} />
                    {w.status}
                </span>
                <span className="readout w-10 text-xs text-muted-foreground">#{w.name}</span>
                <Holder worktree={w} />
                <span className="min-w-0 truncate font-mono text-xs" title={w.branch ?? undefined}>
                    {w.branch ?? (w.detached ? <span className="text-muted-foreground">detached</span> : null)}
                </span>
                <span className="ml-auto flex w-24 shrink-0 justify-end gap-1 text-xs text-muted-foreground">
                    {since && (
                        <>
                            for <Age at={since} />
                        </>
                    )}
                </span>
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pl-[10rem] font-mono text-xs">
                <span className="text-muted-foreground">{w.path}</span>
                {w.processes.length > 0 && (
                    <span className="text-muted-foreground" title="processes treehouse found running in it">
                        {w.processes.map((p) => `${p.name} ${p.pid}`).join(' · ')}
                    </span>
                )}
                {w.branch_error && <span className="text-status-failed">branch unreadable: {w.branch_error}</span>}
                {w.note && <span className="text-status-blocked">{w.note}</span>}
            </div>
        </li>
    )
}

/** What holds a slot: a run's ticket and kind, a review's PR, or treehouse's lease holder as it names it. */
function Holder({ worktree: w }: { worktree: Worktree }) {
    if (w.run) {
        return (
            <span className="flex w-52 shrink-0 items-center gap-2">
                <TicketLink ticketKey={w.run.ticket_key} className="truncate" />
                <Chip>{w.run.kind}</Chip>
                <span className="readout text-xs text-muted-foreground">run:{w.run.id}</span>
            </span>
        )
    }
    if (w.review) {
        return (
            <span className="flex w-52 shrink-0 items-center gap-2">
                <Chip>review</Chip>
                <a
                    href={w.review.pr_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex min-w-0 items-center gap-1 font-mono text-xs text-accent hover:underline"
                >
                    <span className="truncate">{w.review.pr_url.replace(/^https:\/\//, '')}</span>
                    <ExternalLink className="size-3 shrink-0" />
                </a>
            </span>
        )
    }
    return (
        <span className="w-52 shrink-0 truncate font-mono text-xs text-muted-foreground" title={w.holder ?? undefined}>
            {w.holder}
        </span>
    )
}
