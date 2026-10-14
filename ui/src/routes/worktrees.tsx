import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { RotateCw } from 'lucide-react'
import { useState } from 'react'

import { LinkOutIcon } from '@/components/link-out-icon'
import { WORKTREES_REFRESH_MS, worktreesQuery } from '@/api/queries'
import { WORKTREE_STATES } from '@/api/types'
import type { Pool, Worktree, WorktreeState } from '@/api/types'
import { Age } from '@/components/age'
import { CopyButton } from '@/components/copy-button'
import { Counter } from '@/components/counter'
import type { Tone } from '@/components/counter'
import { Notice } from '@/components/notice'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { ListRow, RowLine } from '@/components/rows'
import { Chip } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Button } from '@/components/ui/button'
import { useBranchUrls } from '@/hooks/use-branch-urls'
import { runRef } from '@/lib/refs'
import { overSize, slotsRoot, WORKTREE_DOT, WORKTREE_TEXT } from '@/lib/worktree-state'
import { cn } from '@/lib/utils'

/** Each repository's treehouse pool: its slots, their states, and what holds each one. */
export const Route = createFileRoute('/worktrees')({
    component: WorktreesPage,
})

function WorktreesPage() {
    const { data, error, refetch } = useQuery(worktreesQuery)
    // Only a read the operator asked for shows on the button: the timed one would make it flicker.
    const [reading, setReading] = useState(false)
    const readAgain = async () => {
        setReading(true)
        try {
            await refetch()
        } finally {
            setReading(false)
        }
    }
    return (
        <>
            <PageHeader title="Worktrees">
                Every slot in canopy&apos;s treehouse pools: what holds it, what it has checked out, and what runs in
                it. Paths inside the workspace are shown from its root. Read from treehouse when the page opens and
                whenever a run starts or ends.
            </PageHeader>
            <PoolCounters pools={data} />
            <div className="flex items-center justify-between gap-4">
                <Notice error={error} />
                <Button
                    variant="outline"
                    size="sm"
                    className="ml-auto"
                    onClick={() => void readAgain()}
                    disabled={reading}
                    title={`Read every ${WORKTREES_REFRESH_MS / 1000} seconds while this page is open`}
                    data-testid="worktrees-refresh"
                >
                    <RotateCw />
                    {reading ? 'Reading' : 'Read again'}
                </Button>
            </div>
            {data === undefined ? (
                <Panel>
                    <PanelHeader label="Loading" />
                    <PanelSkeleton className="min-h-40" />
                </Panel>
            ) : (
                data.map((pool) => <PoolPanel key={pool.repo} pool={pool} />)
            )}
        </>
    )
}

/** Every pool at a glance: slots working, held by something else, needing a look, and free. */
function PoolCounters({ pools }: { pools: Pool[] | undefined }) {
    const slots = pools?.flatMap((p) => p.worktrees)
    const count = (state: WorktreeState) => slots?.filter((w) => w.state === state).length
    const dirty = count('dirty')
    const broken = count('broken')
    const look = dirty === undefined || broken === undefined ? undefined : dirty + broken
    // A pool treehouse could not read is a slot count nobody knows: it shows here, in the failure color.
    const unread = pools?.filter((p) => p.error !== null).length ?? 0
    const lookTone: Tone = (broken ?? 0) > 0 || unread > 0 ? 'failed' : (dirty ?? 0) > 0 ? 'blocked' : 'plain'
    const repos = pools?.filter((p) => p.worktrees.some((w) => w.state === 'working')).length
    return (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(12rem,1fr))] gap-3" data-testid="pool-counters">
            <Counter label="Working" value={count('working')} tone="running">
                {repos === undefined ? null : `runs and reviews, in ${repos} ${repos === 1 ? 'pool' : 'pools'}`}
            </Counter>
            <Counter label="Held" value={count('held')} tone="stopped">
                {slots === undefined ? null : 'by a shell, a sync, or another lease'}
            </Counter>
            <Counter label="Needs a look" value={look} tone={lookTone}>
                {look === undefined ? null : looked(dirty ?? 0, broken ?? 0, unread)}
            </Counter>
            <Counter label="Free" value={count('idle')} tone="plain">
                {slots === undefined ? null : `of ${slots.length} slots`}
            </Counter>
        </div>
    )
}

function looked(dirty: number, broken: number, unread: number): string {
    const pools = unread === 0 ? '' : ` · ${unread} ${unread === 1 ? 'pool' : 'pools'} unread`
    return `${dirty} dirty · ${broken} broken${pools}`
}

function PoolPanel({ pool }: { pool: Pool }) {
    const counts = WORKTREE_STATES.map((s) => [s, pool.worktrees.filter((w) => w.state === s).length] as const)
    const over = overSize(pool)
    const root = slotsRoot(pool.worktrees)
    return (
        <Panel data-testid={`pool-${pool.repo}`}>
            <PanelHeader label={pool.repo}>
                <span className="mr-auto ml-3 flex min-w-0 items-center gap-3">
                    <SlotStrip worktrees={pool.worktrees} />
                    {root !== null && (
                        <span className="truncate font-mono text-xs text-muted-foreground" data-testid="pool-root">
                            {root}/
                        </span>
                    )}
                </span>
                <span className="flex items-center gap-3 font-mono text-xs text-muted-foreground">
                    {counts
                        .filter(([, n]) => n > 0)
                        .map(([state, n]) => (
                            <span key={state} className="flex items-center gap-1.5">
                                <WorktreeDot state={state} />
                                <span className="readout">{n}</span> {state}
                            </span>
                        ))}
                    {pool.size !== null && (
                        <span className={cn('readout', over > 0 && 'text-status-blocked')} data-testid="pool-size">
                            {pool.worktrees.length} of size {pool.size}
                        </span>
                    )}
                </span>
            </PanelHeader>
            {over > 0 && (
                <p className="border-b px-3 py-2 text-xs text-status-blocked" data-testid="pool-over">
                    {over === 1 ? '1 slot' : `${over} slots`} past the declared size.{' '}
                    <code className="font-mono">canopy workspace sync</code> removes idle ones; one with work in it
                    stays until it has none.
                </p>
            )}
            {pool.error === null ? (
                pool.worktrees.length === 0 ? (
                    <Empty>no worktrees yet: treehouse makes one when a run or review leases a slot</Empty>
                ) : (
                    <ul className="divide-y" data-testid="worktrees">
                        {pool.worktrees.map((w) => (
                            <WorktreeRow key={w.path} worktree={w} repo={pool.repo} shared={root !== null} />
                        ))}
                    </ul>
                )
            ) : (
                <Notice error={pool.error} className="px-3 py-2.5" />
            )}
        </Panel>
    )
}

/** One square per slot, in slot order, in its state's color: the pool's occupancy at a glance. */
function SlotStrip({ worktrees }: { worktrees: Worktree[] }) {
    if (worktrees.length === 0) {
        return null
    }
    return (
        <span aria-hidden className="flex shrink-0 items-center gap-1" data-testid="slot-strip">
            {worktrees.map((w) => (
                <span
                    key={w.path}
                    title={`#${w.name} ${w.status}`}
                    data-state={w.state}
                    className={cn('inline-flex size-2.5 rounded-[2px]', WORKTREE_DOT[w.state])}
                />
            ))}
        </span>
    )
}

function WorktreeDot({ state }: { state: WorktreeState }) {
    return <span aria-hidden className={cn('inline-flex size-2 shrink-0 rounded-full', WORKTREE_DOT[state])} />
}

/**
 * One slot on one line: its state, number, what holds it, its branch, what runs in it, and for how long. Our state
 * word, with treehouse's own on hover; the slot's path on its number. A note or an unreadable branch gets a second
 * line, since it is something to act on. An idle slot is the state and number alone, muted.
 */
function WorktreeRow({ worktree: w, repo, shared }: { worktree: Worktree; repo: string; shared: boolean }) {
    const branchUrl = useBranchUrls()
    const branchHref = w.branch === null ? undefined : branchUrl(repo, w.branch)
    const since = w.run?.started_at ?? w.review?.started_at ?? w.leased_at
    const idle = w.state === 'idle'
    return (
        <ListRow kind="worktree" className="group/copy py-2" data-testid={`worktree-${w.name}`} data-state={w.state}>
            <span
                className={cn('flex h-5 items-center gap-1.5 font-mono text-xs', WORKTREE_TEXT[w.state])}
                title={`treehouse: ${w.status}`}
            >
                <WorktreeDot state={w.state} />
                {w.state === 'broken' ? w.status : w.state}
            </span>
            <span className="flex items-center">
                <span className="readout w-8 text-xs text-muted-foreground" title={w.path}>
                    #{w.name}
                </span>
                <CopyButton text={w.path} label={`slot ${w.name}'s path`} reveal />
            </span>
            {idle ? <span /> : <Holder worktree={w} />}
            {/* The branch, path, and processes share what the row leaves: each is cut to fit, the age never. */}
            <span className="flex min-w-0 items-center gap-3">
                {!idle && (
                    <>
                        {branchHref === undefined ? (
                            <span className="min-w-0 truncate font-mono text-xs" title={w.branch ?? undefined}>
                                {w.branch ??
                                    (w.detached ? <span className="text-muted-foreground">detached</span> : null)}
                            </span>
                        ) : (
                            <a
                                href={branchHref}
                                target="_blank"
                                rel="noreferrer noopener"
                                title={branchHref}
                                className={cn(
                                    'inline-flex min-w-0 items-center gap-1 font-mono text-xs text-accent',
                                    'underline-offset-4 hover:underline',
                                )}
                            >
                                <span className="truncate">{w.branch}</span>
                                <LinkOutIcon href={branchHref} className="shrink-0" />
                            </a>
                        )}
                        {w.branch !== null && <CopyButton text={w.branch} label="branch" reveal />}
                    </>
                )}
                {!shared && <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">{w.path}</span>}
                {w.processes.length > 0 && <Processes processes={w.processes} />}
            </span>
            <span className="text-right">{since && <Age variant="span" started={since} ended={null} />}</span>
            {(w.note || w.branch_error) && (
                <RowLine from="holder" className="flex flex-wrap gap-x-4 font-mono text-xs">
                    {w.branch_error && (
                        <span className="min-w-0 break-words text-status-failed">
                            branch unreadable: {w.branch_error}
                        </span>
                    )}
                    {w.note && <span className="min-w-0 break-words text-status-blocked">{w.note}</span>}
                </RowLine>
            )}
        </ListRow>
    )
}

/** What holds a slot: a run's ticket and kind, a review's PR, or treehouse's lease holder as it names it. */
function Holder({ worktree: w }: { worktree: Worktree }) {
    if (w.run) {
        return (
            <span className="flex min-w-0 items-center gap-2">
                <TicketLink ticketKey={w.run.ticket_key} className="truncate" />
                <Chip word={w.run.kind} />
                <span className="readout text-xs text-muted-foreground">{runRef(w.run.id)}</span>
            </span>
        )
    }
    if (w.review) {
        return (
            <span className="flex min-w-0 items-center gap-2">
                <Chip>review</Chip>
                <PullRequestLink url={w.review.pr_url} />
            </span>
        )
    }
    return (
        <span className="truncate font-mono text-xs text-muted-foreground" title={w.holder ?? undefined}>
            {w.holder}
        </span>
    )
}

/**
 * The processes treehouse found running in a slot, by name and pid. An agent can start many: they take what the branch
 * leaves, cut to fit, and the whole list is on hover, one to a line.
 */
function Processes({ processes }: { processes: Worktree['processes'] }) {
    const named = processes.map((p) => `${p.name} ${p.pid}`)
    return (
        <span
            className="ml-auto max-w-72 min-w-24 truncate text-right font-mono text-xs text-muted-foreground"
            title={`processes treehouse found running in it:\n${named.join('\n')}`}
            data-testid="worktree-processes"
        >
            {named.join(' · ')}
        </span>
    )
}
