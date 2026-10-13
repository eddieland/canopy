import { useQuery } from '@tanstack/react-query'

import { runsQuery } from '@/api/queries'
import { Age } from '@/components/age'
import { RunLink } from '@/components/run-link'
import { Chip, RunDot } from '@/components/status'
import { workingOn } from '@/lib/run-state'

/**
 * Under a ticket's conversation, on the worker's side: the run working the ticket now, if one is, as a chat shows
 * someone typing. It names the run (opening its page), its kind, what it has cost so far, and for how long it has
 * worked. The runs come whole from the stream, so it appears when a run starts and leaves when it ends.
 */
export function WorkingNow({ ticketKey }: { ticketKey: string }) {
    const runs = workingOn(useQuery(runsQuery).data ?? [], ticketKey)
    return (
        <ul className="stagger flex flex-col gap-1 px-3 empty:hidden" data-testid="working-now" aria-live="polite">
            {runs.map((run) => (
                <li
                    key={run.id}
                    className="flex w-full max-w-2xl items-center gap-2 pb-3 font-mono text-xs text-muted-foreground"
                    data-testid={`working-${run.id}`}
                >
                    <RunDot state="running" />
                    <span className="text-status-running">working now</span>
                    <RunLink id={run.id} />
                    <Chip word={run.kind} />
                    <span className="ml-auto flex items-center gap-3">
                        <span className="readout">{run.cost_usd === null ? '' : `$${run.cost_usd.toFixed(2)}`}</span>
                        <span className="flex items-center gap-1">
                            for <Age at={run.started_at} />
                        </span>
                    </span>
                </li>
            ))}
        </ul>
    )
}
