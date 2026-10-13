import { ExternalLink } from 'lucide-react'
import { useState } from 'react'

import type { Run } from '@/api/types'
import { Age } from '@/components/age'
import { LinkedText } from '@/components/linked-text'
import { RunLink } from '@/components/run-link'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { RUN_TEXT } from '@/lib/run-state'
import type { TicketRuns } from '@/lib/run-state'
import { cn } from '@/lib/utils'

// Where a ticket's row starts what goes under its head line, so it lines up with the ticket's title: past the state's
// column, the key's, and the gap after each.
const UNDER_TITLE = 'pl-[12.5rem]'

/**
 * Runs, one row each: state, the ticket and its title, the run's id (opening its page) and kind, cost, when, and what
 * it said. `ticket` leaves out the ticket and its title, for a ticket's own page.
 */
export function RunsTable({ runs, ticket = true }: { runs: Run[]; ticket?: boolean }) {
    return (
        <ul className="divide-y" data-testid="runs">
            {runs.map((run) => (
                <RunRow key={run.id} run={run} ticket={ticket} />
            ))}
        </ul>
    )
}

/**
 * Runs grouped by ticket, one row each: the ticket's latest run, as `RunsTable` shows it, and a toggle that opens the
 * runs before it, so a ticket that asked twice is one row.
 */
export function TicketRunsTable({ groups }: { groups: TicketRuns[] }) {
    return (
        <ul className="divide-y" data-testid="runs">
            {groups.map((group) => (
                <TicketRow key={group.latest.ticket_key} group={group} />
            ))}
        </ul>
    )
}

function RunRow({ run, ticket }: { run: Run; ticket: boolean }) {
    return (
        <li className="flex flex-col gap-1 px-3 py-2.5" data-testid={`run-${run.id}`}>
            <RunBody run={run} ticket={ticket} />
        </li>
    )
}

function TicketRow({ group }: { group: TicketRuns }) {
    const [open, setOpen] = useState(false)
    const { latest, earlier } = group
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <li className="flex flex-col gap-1 px-3 py-2.5" data-testid={`run-${latest.id}`}>
                <RunBody run={latest} ticket />
                {earlier.length > 0 && (
                    <>
                        <div className={UNDER_TITLE}>
                            <CollapsibleTrigger
                                className={cn(
                                    'rounded-sm font-mono text-xs text-accent underline-offset-4 outline-none',
                                    'hover:underline focus-visible:ring-3 focus-visible:ring-ring/50',
                                )}
                            >
                                {open
                                    ? 'hide earlier runs'
                                    : `${earlier.length} earlier ${earlier.length === 1 ? 'run' : 'runs'}`}
                            </CollapsibleTrigger>
                        </div>
                        <CollapsibleContent asChild>
                            <ul
                                className="flex flex-col gap-1.5 pt-1"
                                data-testid={`earlier-runs-${latest.ticket_key}`}
                            >
                                {earlier.map((run) => (
                                    <EarlierRow key={run.id} run={run} />
                                ))}
                            </ul>
                        </CollapsibleContent>
                    </>
                )}
            </li>
        </Collapsible>
    )
}

/**
 * One of a ticket's earlier runs, on one line in the columns of the row it sits in: its state, the first line of what
 * it said where the title is, its id and chips, cost, and when. The rest is on the run's page.
 */
function EarlierRow({ run }: { run: Run }) {
    const said = run.summary?.split('\n', 1)[0] ?? ''
    return (
        <li className="flex items-center gap-3" data-testid={`run-${run.id}`}>
            <RunStatus run={run} />
            <span className="w-24 shrink-0" />
            <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground" title={said || undefined}>
                <LinkedText text={said} />
            </span>
            <span className="flex w-56 shrink-0 items-center gap-3">
                <RunFacts run={run} />
            </span>
            <RunReadouts run={run} />
        </li>
    )
}

function RunBody({ run, ticket }: { run: Run; ticket: boolean }) {
    const indent = ticket ? UNDER_TITLE : 'pl-[6.75rem]'
    return (
        <>
            <div className="flex items-center gap-3">
                <RunStatus run={run} />
                {ticket ? (
                    <>
                        <TicketLink ticketKey={run.ticket_key} className="w-24 shrink-0 truncate" />
                        <TicketTitle title={run.ticket_title} className="flex-1" />
                        {/* Fixed width, so every row's run id lines up, whatever chips follow it. */}
                        <span className="flex w-56 shrink-0 items-center gap-3">
                            <RunFacts run={run} />
                        </span>
                    </>
                ) : (
                    <RunFacts run={run} />
                )}
                <RunReadouts run={run} />
            </div>
            {run.summary && <RichText text={run.summary} lines={SUMMARY_LINES} className={indent} />}
            {(run.prs.length > 0 || run.worktrees.length > 0 || run.session_id) && (
                <div className={cn('flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs', indent)}>
                    {run.prs.map((pr) => (
                        <a
                            key={pr}
                            href={pr}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="inline-flex items-center gap-1 text-accent underline-offset-4 hover:underline"
                        >
                            {pr.replace(/^https:\/\//u, '')}
                            <ExternalLink className="size-3" />
                        </a>
                    ))}
                    {run.worktrees.map((path) => (
                        <span key={path} className="text-muted-foreground" title="the worktree it holds">
                            {path}
                        </span>
                    ))}
                    {run.session_id && (
                        <span className="text-muted-foreground" title="its transcript is on the run's page">
                            session {run.session_id}
                        </span>
                    )}
                </div>
            )}
        </>
    )
}

function RunFacts({ run }: { run: Run }) {
    return (
        <>
            <RunLink id={run.id} className="w-14" />
            <Chip word={run.kind} />
            {run.private && <Chip>private</Chip>}
        </>
    )
}

function RunStatus({ run }: { run: Run }) {
    return (
        <span className={cn('flex w-20 shrink-0 items-center gap-1.5 font-mono text-xs', RUN_TEXT[run.state])}>
            <RunDot state={run.state} />
            {run.status}
        </span>
    )
}

function RunReadouts({ run }: { run: Run }) {
    return (
        <span className="ml-auto flex items-center gap-4">
            <span className="readout w-16 text-right text-xs text-muted-foreground" data-testid="run-cost">
                {run.cost_usd === null ? '' : `$${run.cost_usd.toFixed(2)}`}
            </span>
            <span className="flex w-24 justify-end gap-1 text-xs text-muted-foreground">
                {run.ended_at === null ? 'for' : 'ended'}
                <Age at={run.ended_at ?? run.started_at} />
                {run.ended_at === null ? '' : 'ago'}
            </span>
        </span>
    )
}
