import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { RotateCw } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { LinkOutIcon } from '@/components/link-out-icon'
import { WORKTREES_REFRESH_MS, worktreesQuery } from '@/api/queries'
import { WORKTREE_STATES } from '@/api/types'
import type { Pool, Worktree, WorktreeState } from '@/api/types'
import { Age } from '@/components/age'
import { CopyButton } from '@/components/copy-button'
import { Disclosure } from '@/components/disclosure'
import { Notice } from '@/components/notice'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { PoolCounters } from '@/components/pool-counters'
import { PullRequestLink } from '@/components/pull-request-link'
import { ListRow, RowGrid, RowLine } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { Chip } from '@/components/status'
import { TaskLink, TaskRunLink } from '@/components/task-link'
import { TicketLink } from '@/components/ticket-link'
import { Clipped, Tip } from '@/components/tip'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { useBranchUrls } from '@/hooks/use-branch-urls'
import { useWholePath } from '@/hooks/use-whole-path'
import { slotRef } from '@/lib/refs'
import { useNow } from '@/lib/time'
import {
    overSize,
    poolsLine,
    poolShown,
    slotGroups,
    slotsRoot,
    WORKTREE_DOT,
    WORKTREE_TEXT,
} from '@/lib/worktree-state'
import { cn } from '@/lib/utils'
import { runKind } from '@/lib/words'

// What the page shows, the same on every visit: the title's help, so the description is left for the pools' state.
const HELP =
    "Every slot in canopy's pools: what holds it, what it has checked out, and what runs in it. Paths inside the " +
    'workspace are shown from its root. Read when the page opens, whenever a run starts or ends, and every ' +
    `${WORKTREES_REFRESH_MS / 1000} seconds while it is open.`

interface WorktreesSearch {
    state?: WorktreeState | undefined
}

/**
 * Each repository's pool of worktrees: its slots, their states, and what holds each one. `?state=` keeps the slots in
 * that state, and the pools that have one.
 */
export const Route = createFileRoute('/workspace/worktrees')({
    // Typed search params, as the runs page's: every key returned, undefined when it is not a state.
    validateSearch: (search: Record<string, unknown>): WorktreesSearch => ({
        state: WORKTREE_STATES.find((s) => s === search['state']),
    }),
    component: WorktreesPage,
})

function WorktreesPage() {
    const { state } = Route.useSearch()
    const query = useQuery(worktreesQuery)
    const { data, dataUpdatedAt, error, refetch } = query
    const now = useNow()
    const shown = data?.filter((pool) => poolShown(pool, state))
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
            <PageHeader title="Worktrees" help={HELP}>
                {data === undefined
                    ? query.isPending
                        ? 'reading the pools'
                        : null
                    : poolsLine(data, dataUpdatedAt, now)}
            </PageHeader>
            <PoolCounters pools={data} />
            {/* One panel of every pool, so the read that covers them all sits in its header, as All open does. */}
            <Panel data-testid="pools">
                <PanelHeader label="Pools">
                    <span className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
                        {/* A workspace of many repositories is mostly idle slots: this finds the few that are not. */}
                        <nav aria-label="Filter by state" className="flex flex-wrap items-center gap-1">
                            <FilterLink search={{ state: undefined }}>all</FilterLink>
                            {WORKTREE_STATES.map((s) => (
                                <FilterLink key={s} search={{ state: s }}>
                                    <WorktreeDot state={s} />
                                    {s}
                                </FilterLink>
                            ))}
                        </nav>
                        <Button
                            variant="ghost"
                            size="xs"
                            onClick={() => void readAgain()}
                            disabled={reading}
                            title={`Read every ${WORKTREES_REFRESH_MS / 1000} seconds while this page is open`}
                            data-testid="worktrees-refresh"
                        >
                            <RotateCw />
                            {reading ? 'Reading' : 'Read again'}
                        </Button>
                        <span className="readout text-xs text-muted-foreground">{shown?.length}</span>
                    </span>
                </PanelHeader>
                {/* A failed read keeps the pools on screen, under why; with none yet, it says why in their place. */}
                {data !== undefined && <Notice error={error} className="border-b px-3 py-2" />}
                {shown === undefined ? (
                    <PanelLoading query={query} className="min-h-40" />
                ) : shown.length === 0 && state !== undefined ? (
                    <Empty>no {state} slots now: no pool has one</Empty>
                ) : shown.length === 0 ? (
                    <Empty>
                        no pools yet: <code className="font-mono text-xs">canopy workspace sync</code> makes one for
                        each repository
                    </Empty>
                ) : (
                    <div className="divide-y">
                        {shown.map((pool) => (
                            <PoolSection key={pool.repo} pool={pool} state={state} />
                        ))}
                    </div>
                )}
            </Panel>
        </>
    )
}

/** A filter chip, selected when it matches the validated search: an unknown `?state=` selects `all`. */
function FilterLink({ search, children }: { search: WorktreesSearch; children: ReactNode }) {
    const { state } = Route.useSearch()
    return (
        <Link
            to="/workspace/worktrees"
            search={search}
            data-selected={search.state === state}
            className={cn(
                'flex h-6 items-center gap-1.5 rounded-sm px-2 font-mono text-xs text-muted-foreground',
                'hover:bg-surface-raised hover:text-foreground',
                'data-[selected=true]:bg-accent/16 data-[selected=true]:text-foreground',
            )}
        >
            {children}
        </Link>
    )
}

/**
 * One pool in the Pools panel: its header, any slots past its size, and a line per slot, or per run of idle ones. With
 * a `state`, the lines of the slots in it alone; the header still counts every slot.
 */
function PoolSection({ pool, state }: { pool: Pool; state: WorktreeState | undefined }) {
    const counts = WORKTREE_STATES.map((s) => [s, pool.worktrees.filter((w) => w.state === s).length] as const)
    const over = overSize(pool)
    const root = slotsRoot(pool.worktrees)
    return (
        <section aria-label={pool.repo} data-testid={`pool-${pool.repo}`}>
            <PoolHeader repo={pool.repo}>
                <span className="mr-auto ml-3 flex min-w-0 items-center gap-3">
                    <SlotStrip worktrees={pool.worktrees} />
                    {root !== null && (
                        <span className="truncate font-mono text-xs text-muted-foreground" data-testid="pool-root">
                            {root}/
                        </span>
                    )}
                </span>
                {/* Each count whole: in a narrow panel they wrap, one under another, never a count split. */}
                <span
                    className={cn(
                        'flex flex-wrap items-center justify-end gap-x-3 font-mono text-xs whitespace-nowrap',
                        'text-muted-foreground',
                    )}
                >
                    {counts
                        .filter(([, n]) => n > 0)
                        .map(([counted, n]) => (
                            <span key={counted} className="flex items-center gap-1.5">
                                <WorktreeDot state={counted} />
                                <span className="readout">{n}</span> {counted}
                            </span>
                        ))}
                    {pool.size !== null && (
                        <span className={cn('readout', over > 0 && 'text-status-blocked')} data-testid="pool-size">
                            {pool.worktrees.length} of size {pool.size}
                        </span>
                    )}
                </span>
            </PoolHeader>
            {over > 0 && (
                <p className="border-b px-3 py-2 text-xs text-status-blocked" data-testid="pool-over">
                    {over === 1 ? '1 slot' : `${over} slots`} past the declared size.{' '}
                    <code className="font-mono">canopy workspace sync</code> removes idle ones; one with work in it
                    stays until it has none.
                </p>
            )}
            {pool.error === null ? (
                pool.worktrees.length === 0 ? (
                    <Empty>no worktrees yet: the pool makes one when a run or review leases a slot</Empty>
                ) : (
                    <ul className="divide-y" data-testid="worktrees">
                        {slotGroups(pool.worktrees, state).map((group) =>
                            group.kind === 'slot' ? (
                                <WorktreeRow
                                    key={group.worktree.path}
                                    worktree={group.worktree}
                                    repo={pool.repo}
                                    shared={root !== null}
                                />
                            ) : (
                                <IdleSlots
                                    key={`idle ${group.worktrees[0]?.path}`}
                                    worktrees={group.worktrees}
                                    repo={pool.repo}
                                    shared={root !== null}
                                />
                            ),
                        )}
                    </ul>
                )
            ) : (
                <Notice error={pool.error} className="px-3 py-2.5" />
            )}
        </section>
    )
}

/** A pool's head line inside the Pools panel: its repository, then what follows, on the panel's own surface. */
function PoolHeader({ repo, children }: { repo: string; children: ReactNode }) {
    return (
        <div className="flex min-h-9 items-center justify-between gap-3 border-b px-3 py-0.5">
            <span className="panel-label font-medium text-foreground">{repo}</span>
            {children}
        </div>
    )
}

/**
 * One square per slot, in slot order, in its state's color: the pool's occupancy at a glance. A pool of many slots
 * wraps its squares onto more lines rather than pushing past the panel's edge.
 */
function SlotStrip({ worktrees }: { worktrees: Worktree[] }) {
    if (worktrees.length === 0) {
        return null
    }
    return (
        <span aria-hidden className="flex min-w-0 flex-wrap items-center gap-1 py-1" data-testid="slot-strip">
            {worktrees.map((w) => (
                <span
                    key={w.path}
                    title={`${slotRef(w.name)} ${w.status}`}
                    data-state={w.state}
                    className={cn('inline-flex size-2.5 rounded-xs', WORKTREE_DOT[w.state])}
                />
            ))}
        </span>
    )
}

/**
 * A run of idle slots in a row, folded into one line: the state, then how many and which, a toggle in the accent that
 * opens each slot's own line under it. A pool of many slots is mostly idle ones; folded, those with work stay in reach.
 */
function IdleSlots({ worktrees, repo, shared }: { worktrees: Worktree[]; repo: string; shared: boolean }) {
    const [open, setOpen] = useState(false)
    const first = worktrees[0]?.name
    const last = worktrees.at(-1)?.name
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <li data-testid={`idle-slots-${first}`} data-state="idle">
                <RowGrid kind="worktree" className="items-center py-2">
                    <span className={cn('flex h-5 items-center gap-1.5 font-mono text-xs', WORKTREE_TEXT.idle)}>
                        <WorktreeDot state="idle" />
                        idle
                    </span>
                    <RowLine from="slot" className="flex items-center">
                        <Disclosure
                            open={open}
                            what={`${worktrees.length} slots, ${slotRef(first ?? '')} to ${slotRef(last ?? '')}`}
                            // In line with the slot numbers above and below it, and no taller than a line of text.
                            className="-my-1 -ml-2"
                        />
                    </RowLine>
                </RowGrid>
                <CollapsibleContent asChild>
                    <ul className="divide-y border-t">
                        {worktrees.map((w) => (
                            <WorktreeRow key={w.path} worktree={w} repo={repo} shared={shared} />
                        ))}
                    </ul>
                </CollapsibleContent>
            </li>
        </Collapsible>
    )
}

function WorktreeDot({ state }: { state: WorktreeState }) {
    return <span aria-hidden className={cn('inline-flex size-2 shrink-0 rounded-full', WORKTREE_DOT[state])} />
}

/**
 * One slot on one line: its state, number, what holds it, its branch, what runs in it, and for how long. Our state
 * word, with the pool's own in its tip; the slot's path in its number's. A note or an unreadable branch gets a second
 * line, since it is something to act on. An idle slot is the state and number alone, muted.
 */
function WorktreeRow({ worktree: w, repo, shared }: { worktree: Worktree; repo: string; shared: boolean }) {
    const branchUrl = useBranchUrls()
    const branchHref = w.branch === null ? undefined : branchUrl(repo, w.branch)
    const whole = useWholePath()
    const since = w.run?.started_at ?? w.review?.started_at ?? w.task?.started_at ?? w.leased_at
    const idle = w.state === 'idle'
    return (
        <ListRow kind="worktree" className="group/copy py-2" data-testid={`worktree-${w.name}`} data-state={w.state}>
            <Tip fact={`pool: ${w.status}`} mono>
                <span className={cn('flex h-5 items-center gap-1.5 font-mono text-xs', WORKTREE_TEXT[w.state])}>
                    <WorktreeDot state={w.state} />
                    {w.state === 'broken' ? w.status : w.state}
                </span>
            </Tip>
            <span className="flex items-center">
                <Tip fact={w.path} mono>
                    <span className="readout w-8 text-xs text-muted-foreground">{slotRef(w.name)}</span>
                </Tip>
                {whole && <CopyButton text={whole(w.path)} label={`slot ${w.name}'s path`} reveal />}
            </span>
            {idle ? <span /> : <Holder worktree={w} />}
            {/* The branch, path, and processes share what the row leaves: each is cut to fit, the age never. */}
            <span className="flex min-w-0 items-center gap-3">
                {!idle && (
                    <>
                        {branchHref === undefined ? (
                            <Clipped text={w.branch ?? ''} mono className="min-w-0 font-mono text-xs">
                                {w.branch ??
                                    (w.detached ? <span className="text-muted-foreground">detached</span> : null)}
                            </Clipped>
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

/**
 * What holds a slot: a run's ticket and kind, a review's PR, a task's run, or the lease holder as the pool names it. A
 * run's ticket and id stay whole; its kind is what gets cut, whole in its tip, since a resume's reasons can run long.
 * A task's run is its task and the run, as a ticket's is its ticket and the run.
 */
function Holder({ worktree: w }: { worktree: Worktree }) {
    if (w.run) {
        return (
            <span className="flex min-w-0 items-center gap-2">
                <TicketLink ticketKey={w.run.ticket_key} className="shrink-0" />
                <Chip word={runKind(w.run)} className="min-w-0 shrink" />
                <RunLink id={w.run.id} className="shrink-0" />
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
    if (w.task) {
        return (
            <span className="flex min-w-0 items-center gap-2">
                <TaskLink id={w.task.task_id} className="shrink-0" />
                <TaskRunLink task={w.task.task_id} run={w.task.run_id} className="shrink-0" />
            </span>
        )
    }
    return <Clipped text={w.holder ?? ''} mono className="font-mono text-xs text-muted-foreground" />
}

/**
 * The processes the pool found running in a slot, by name and pid. An agent can start many: they take what the branch
 * leaves, cut to fit, and the whole list is in a tip, one to a line.
 */
function Processes({ processes }: { processes: Worktree['processes'] }) {
    const named = processes.map((p) => `${p.name} ${p.pid}`)
    return (
        <Tip fact={`processes the pool found running in it:\n${named.join('\n')}`} mono>
            <span
                className="ml-auto max-w-72 min-w-24 truncate text-right font-mono text-xs text-muted-foreground"
                data-testid="worktree-processes"
            >
                {named.join(' · ')}
            </span>
        </Tip>
    )
}
