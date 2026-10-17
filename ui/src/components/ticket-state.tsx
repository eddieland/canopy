import type { TicketSummary } from '@/api/types'
import { RunDot } from '@/components/status'
import { runRef } from '@/lib/refs'
import { RUN_TEXT } from '@/lib/run-state'
import { cn } from '@/lib/utils'

const LINE = 'flex items-center gap-1.5 font-mono text-xs'

/**
 * Where a ticket stands, the tickets list's leading column: the run working it and the question waiting on the
 * operator, each with its run's dot, else `done` or `open`, so every row has a dot and the column is never blank.
 */
export function TicketState({ ticket }: { ticket: Pick<TicketSummary, 'running_run' | 'awaiting' | 'done'> }) {
    const idle = ticket.running_run === null && ticket.awaiting === null
    const settled = ticket.done ? 'done' : 'stopped'
    return (
        <span className="flex flex-col gap-0.5 whitespace-nowrap">
            {ticket.running_run !== null && (
                <span className={cn(LINE, RUN_TEXT.running)}>
                    <RunDot state="running" />
                    {runRef(ticket.running_run)}
                </span>
            )}
            {ticket.awaiting !== null && (
                <span className={cn(LINE, RUN_TEXT.blocked)}>
                    <RunDot state="blocked" />
                    waiting on you
                </span>
            )}
            {idle && (
                <span className={cn(LINE, RUN_TEXT[settled])}>
                    <RunDot state={settled} />
                    {ticket.done ? 'done' : 'open'}
                </span>
            )}
        </span>
    )
}
