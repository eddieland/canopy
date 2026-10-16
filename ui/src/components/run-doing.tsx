import type { RunActivity } from '@/api/types'
import { Age } from '@/components/age'
import { cn } from '@/lib/utils'

/**
 * What a running run did last, on one line (DESIGN §8): its latest tool call's tool, what the call did (a shell
 * call's command, else the runtime's title; whole on hover), and how long ago. Agent output, rendered as text.
 */
export function RunDoing({ activity, className }: { activity: RunActivity; className?: string }) {
    return (
        <span
            className={cn('flex min-w-0 items-center gap-2 font-mono text-xs text-muted-foreground', className)}
            data-testid="run-doing"
        >
            <span className="shrink-0 text-status-running" title="its latest tool call">
                {activity.tool}
            </span>
            {activity.did !== '' && (
                <span className="min-w-0 truncate" title={activity.did}>
                    {activity.did}
                </span>
            )}
            <Age at={activity.at} variant="ago" className="shrink-0" />
        </span>
    )
}
