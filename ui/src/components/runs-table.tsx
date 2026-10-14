import { useState } from 'react'

import { LinkOutIcon } from '@/components/link-out-icon'
import type { Run } from '@/api/types'
import { Ended } from '@/components/age'
import { LinkedText } from '@/components/linked-text'
import { ListRow, RowLine } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { rowLineFrom } from '@/lib/rows'
import { RUN_TEXT } from '@/lib/run-state'
import type { TicketRuns } from '@/lib/run-state'
import { cn } from '@/lib/utils'

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
        <ListRow kind={ticket ? 'run' : 'own-run'} data-testid={`run-${run.id}`}>
            <RunBody run={run} ticket={ticket} />
        </ListRow>
    )
}

function TicketRow({ group }: { group: TicketRuns }) {
    const [open, setOpen] = useState(false)
    const { latest, earlier } = group
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <ListRow kind="run" data-testid={`run-${latest.id}`}>
                <RunBody run={latest} ticket />
                {earlier.length > 0 && (
                    <>
                        <RowLine from="title">
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
                        </RowLine>
                        <CollapsibleContent asChild>
                            <ul
                                className={cn('flex flex-col gap-1.5 pt-1', rowLineFrom('state'))}
                                data-testid={`earlier-runs-${latest.ticket_key}`}
                            >
                                {earlier.map((run) => (
                                    <EarlierRow key={run.id} run={run} />
                                ))}
                            </ul>
                        </CollapsibleContent>
                    </>
                )}
            </ListRow>
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
        <ListRow kind="run" className="p-0" data-testid={`run-${run.id}`}>
            <RunStatus run={run} />
            <span />
            <span className="truncate text-sm text-muted-foreground" title={said || undefined}>
                <LinkedText text={said} />
            </span>
            <span className="flex items-center gap-3">
                <RunFacts run={run} />
            </span>
            <RunReadouts run={run} />
        </ListRow>
    )
}

function RunBody({ run, ticket }: { run: Run; ticket: boolean }) {
    // What goes under the head line starts under the ticket's title, or under the run's id on its subject's page.
    const under = ticket ? 'title' : 'facts'
    return (
        <>
            <RunStatus run={run} />
            {ticket && (
                <>
                    <TicketLink ticketKey={run.ticket_key} className="truncate" />
                    <TicketTitle title={run.ticket_title} />
                </>
            )}
            <span className="flex items-center gap-3">
                <RunFacts run={run} />
            </span>
            <RunReadouts run={run} />
            {run.summary && <RichText text={run.summary} lines={SUMMARY_LINES} className={rowLineFrom(under)} />}
            {(run.prs.length > 0 || run.worktrees.length > 0 || run.session_id) && (
                <RowLine from={under} className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs">
                    {run.prs.map((pr) => (
                        <a
                            key={pr}
                            href={pr}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="inline-flex items-center gap-1 text-accent underline-offset-4 hover:underline"
                        >
                            {pr.replace(/^https:\/\//u, '')}
                            <LinkOutIcon href={pr} />
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
                </RowLine>
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
        <span className={cn('flex items-center gap-1.5 font-mono text-xs', RUN_TEXT[run.state])}>
            <RunDot state={run.state} />
            {run.status}
        </span>
    )
}

/** A run's cost and when, a cell each, in the row's `cost` and `age` columns. */
function RunReadouts({ run }: { run: Run }) {
    return (
        <>
            <span className="readout text-right text-xs text-muted-foreground" data-testid="run-cost">
                {run.cost_usd === null ? '' : `$${run.cost_usd.toFixed(2)}`}
            </span>
            <Ended started={run.started_at} ended={run.ended_at} />
        </>
    )
}
