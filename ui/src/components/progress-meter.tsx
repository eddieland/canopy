import type { RunCard } from '@/api/types'
import { checklist } from '@/lib/progress'
import type { ItemStatus } from '@/lib/progress'
import { useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

/**
 * A run's steps as a bar of segments, one each, in its status's color. Only a done step fills its segment, in
 * `status-done`, so the filled segments are the count beside the meter; working fills half of the track in
 * `status-running`, a barber pole sweeping across its segment while the run runs, blocked or stuck half in
 * `muted-foreground`, to do is the bare track, skipped the track fainter still. Drawn, so its words are its label.
 */
export function ProgressMeter({ card, running, className }: { card: RunCard; running: boolean; className?: string }) {
    const items = checklist(card, useNow())
    const done = items.filter((i) => i.status === 'done').length
    const counted = items.filter((i) => i.status !== 'skipped').length
    return (
        <span className={cn('flex h-1.5 min-w-0 gap-0.5', className)} data-testid="progress-meter">
            <span className="sr-only">{`${done} of ${counted} steps done`}</span>
            {items.map((item, i) => (
                <span
                    key={`${i}-${item.title}`}
                    aria-hidden
                    className={cn('h-full min-w-1 flex-1 overflow-hidden rounded-xs', SEGMENT[item.status])}
                >
                    {HALF[item.status] !== undefined && (
                        <span
                            className={cn(
                                'block h-full w-1/2',
                                HALF[item.status],
                                running && item.status === 'working' && 'animate-barber',
                            )}
                        />
                    )}
                </span>
            ))}
        </span>
    )
}

/** Each status's segment: done filled, the rest the track, fainter for skipped. */
const SEGMENT: Record<ItemStatus, string> = {
    done: 'bg-status-done',
    working: 'bg-border',
    stuck: 'bg-border',
    blocked: 'bg-border',
    not_started: 'bg-border',
    skipped: 'bg-border/40',
}

/** The half of the track a step under way fills, so it never reads as done. */
const HALF: Partial<Record<ItemStatus, string>> = {
    working: 'bg-status-running',
    stuck: 'bg-muted-foreground',
    blocked: 'bg-muted-foreground',
}
