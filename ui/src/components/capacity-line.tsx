import type { Capacity } from '@/api/types'
import { Tip } from '@/components/tip'
import { cn } from '@/lib/utils'

/**
 * What runs now against each limit of `[capacity]`, as the harness counts it when it refuses a start: the worker runs,
 * reviews, and task runs against `max_workers`, of which `tasks` are task runs, the reviews against `max_reviews`
 * within it, and the chores against `max_chores`. A limit that is full says so: the next dispatch of its kind waits
 * for a run to end.
 */
export function CapacityLine({
    capacity,
    busy: running,
    tasks,
}: {
    capacity: Capacity
    busy: Capacity
    tasks: number
}) {
    return (
        <p className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs" data-testid="runs-capacity">
            <Limit
                name="workers"
                running={running.workers}
                limit={capacity.workers}
                fact={
                    `capacity.max_workers: worker runs, reviews, and task runs at once ` +
                    `(${running.reviews} running a review, ${tasks} a task)`
                }
            />
            <Limit
                name="reviews"
                running={running.reviews}
                limit={capacity.reviews}
                fact="capacity.max_reviews: reviews at once, within max_workers"
            />
            <Limit
                name="chores"
                running={running.chores}
                limit={capacity.chores}
                fact="capacity.max_chores: chore runs at once, apart from max_workers"
            />
        </p>
    )
}

function Limit({ name, running, limit, fact }: { name: string; running: number; limit: number; fact: string }) {
    // A limit of 0 turns its kind off: nothing waits on it, so it is not full.
    const full = limit > 0 && running >= limit
    return (
        <Tip fact={fact} mono>
            <span
                className={cn('readout', full ? 'text-status-blocked' : 'text-muted-foreground')}
                data-testid={`capacity-${name}`}
            >
                {name} {limit === 0 ? 'off' : `${running} of ${limit}`}
                {full && ' · full'}
            </span>
        </Tip>
    )
}
