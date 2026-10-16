import { useQuery } from '@tanstack/react-query'

import { runsQuery } from '@/api/queries'
import { Age } from '@/components/age'
import { Cost } from '@/components/cost'
import { RunDoing } from '@/components/run-doing'
import { RunLink } from '@/components/run-link'
import { Chip, RunDot } from '@/components/status'
import { workingOn } from '@/lib/run-state'

/**
 * Under a ticket's conversation, on the worker's side: the run working the ticket now, if one is, as a chat shows
 * someone typing. It names the run (opening its page), its kind, its latest tool call, what it has cost so far, and
 * for how long it has worked. The runs come whole from the stream, so it appears when a run starts, follows what it
 * does, and leaves when it ends.
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
                    {run.activity && <RunDoing activity={run.activity} />}
                    <span className="ml-auto flex shrink-0 items-center gap-3">
                        <Cost usd={run.cost_usd} />
                        <Age variant="span" started={run.started_at} ended={null} />
                    </span>
                </li>
            ))}
        </ul>
    )
}
