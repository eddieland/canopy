import { ExternalLink } from 'lucide-react'
import { useState } from 'react'

import type { Run } from '@/api/types'
import { Age } from '@/components/age'
import { RunLink } from '@/components/run-link'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { RUN_TEXT, type TicketRuns } from '@/lib/run-state'
import { cn } from '@/lib/utils'

// Where a ticket's row puts what goes under its head line, so it starts under the ticket's title: the state's column,
// the key's, and the gaps after each. Written out in full so Tailwind finds them.
const UNDER_TITLE = { pad: 'pl-[12.5rem]', margin: 'ml-[12.5rem]' }

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
        <li className="flex flex-col gap-1 px-3 py-2.5" data-testid={`run-${latest.id}`}>
            <RunBody run={latest} ticket />
            {earlier.length > 0 && (
                <div className={UNDER_TITLE.pad}>
                    <button
                        type="button"
                        aria-expanded={open}
                        onClick={() => setOpen(!open)}
                        className={cn(
                            'rounded-sm font-mono text-xs text-accent underline-offset-4 outline-none',
                            'hover:underline focus-visible:ring-3 focus-visible:ring-ring/50',
                        )}
                    >
                        {open
                            ? 'hide earlier runs'
                            : `${earlier.length} earlier ${earlier.length === 1 ? 'run' : 'runs'}`}
                    </button>
                </div>
            )}
            {open && (
                <ul
                    className={cn(UNDER_TITLE.margin, 'divide-y border-l')}
                    data-testid={`earlier-runs-${latest.ticket_key}`}
                >
                    {earlier.map((run) => (
                        <RunRow key={run.id} run={run} ticket={false} />
                    ))}
                </ul>
            )}
        </li>
    )
}

function RunBody({ run, ticket }: { run: Run; ticket: boolean }) {
    const indent = ticket ? UNDER_TITLE.pad : 'pl-[6.75rem]'
    return (
        <>
            <div className="flex items-center gap-3">
                <span className={cn('flex w-20 items-center gap-1.5 font-mono text-xs', RUN_TEXT[run.state])}>
                    <RunDot state={run.state} />
                    {run.status}
                </span>
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
                            {pr.replace(/^https:\/\//, '')}
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
