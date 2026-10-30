import type { Pool, WorktreeState } from '@/api/types'
import { Counter } from '@/components/counter'
import type { Tone } from '@/components/counter'
import { heldBy, needsLook, workingLine } from '@/lib/worktree-state'

/**
 * Every pool at a glance: slots working, held by something else, needing a look, and free. A skeleton in each until
 * the pools are read.
 */
export function PoolCounters({ pools }: { pools: Pool[] | undefined }) {
    const slots = pools?.flatMap((p) => p.worktrees)
    const count = (state: WorktreeState) => slots?.filter((w) => w.state === state).length
    const look = pools === undefined ? undefined : needsLook(pools)
    // A broken slot, or a pool that could not be read, is a slot nobody can vouch for: the failure color.
    const failed = (count('broken') ?? 0) > 0 || (pools ?? []).some((p) => p.error !== null)
    const lookTone: Tone = failed ? 'failed' : (count('dirty') ?? 0) > 0 ? 'blocked' : 'plain'
    return (
        // Four across once the pane gives each 11rem (4 × 11rem and three 0.75rem gaps), else two by two: never three
        // and one. The pane is the container, so the rail's width counts.
        <div className="@container">
            <div className="grid grid-cols-2 gap-3 @min-[46.25rem]:grid-cols-4" data-testid="pool-counters">
                <Counter label="Working" value={count('working')} tone="running">
                    {pools === undefined ? null : workingLine(pools)}
                </Counter>
                <Counter label="Held" value={count('held')} tone="stopped">
                    {slots === undefined ? null : heldBy(slots)}
                </Counter>
                <Counter label="Needs a look" value={look?.count} tone={lookTone}>
                    {look?.text ?? null}
                </Counter>
                <Counter label="Free" value={count('idle')} tone="plain">
                    {slots === undefined ? null : `of ${slots.length} slots`}
                </Counter>
            </div>
        </div>
    )
}
