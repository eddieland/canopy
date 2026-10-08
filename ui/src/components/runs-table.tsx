import { ExternalLink } from 'lucide-react'

import type { Run } from '@/api/types'
import { Age } from '@/components/age'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { RUN_TEXT } from '@/lib/run-state'
import { cn } from '@/lib/utils'

/** Runs, one row each: state, id, ticket, kind, when, cost, and what it said. `ticket` leaves out the ticket column. */
export function RunsTable({ runs, ticket = true }: { runs: Run[]; ticket?: boolean }) {
    return (
        <ul className="divide-y" data-testid="runs">
            {runs.map((run) => (
                <RunRow key={run.id} run={run} ticket={ticket} />
            ))}
        </ul>
    )
}

function RunRow({ run, ticket }: { run: Run; ticket: boolean }) {
    return (
        <li className="flex flex-col gap-1 px-3 py-2.5" data-testid={`run-${run.id}`}>
            <div className="flex items-center gap-3">
                <span className={cn('flex w-20 items-center gap-1.5 font-mono text-xs', RUN_TEXT[run.state])}>
                    <RunDot state={run.state} />
                    {run.status}
                </span>
                <span className="readout w-14 text-xs text-muted-foreground">run:{run.id}</span>
                {ticket && <TicketLink ticketKey={run.ticket_key} className="w-24 truncate" />}
                <Chip>{run.kind}</Chip>
                {run.private && <Chip>private</Chip>}
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
            {run.summary && <p className="pl-[6.75rem] text-sm break-words">{run.summary}</p>}
            {(run.prs.length > 0 || run.worktrees.length > 0 || run.session_id) && (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pl-[6.75rem] font-mono text-xs">
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
                        <span className="text-muted-foreground" title="open its transcript with the runtime's tools">
                            session {run.session_id}
                        </span>
                    )}
                </div>
            )}
        </li>
    )
}
