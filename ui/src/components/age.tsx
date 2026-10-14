import { age, localTime, useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

/** How long ago `at` was, as a fixed-width readout, with the local time on hover. */
export function Age({ at, className }: { at: string; className?: string }) {
    const now = useNow()
    return (
        <time dateTime={at} title={localTime(at)} className={cn('readout text-xs text-muted-foreground', className)}>
            {age(at, now)}
        </time>
    )
}

/**
 * When something that runs ended, `ended 3m ago`, or while it still runs, `for 3m`: a run's, a tick's, a chore run's.
 * Right-aligned, for a list's `age` column.
 */
export function Ended({ started, ended }: { started: string; ended: string | null }) {
    return (
        <span className="flex justify-end gap-1 text-xs text-muted-foreground">
            {ended === null ? 'for' : 'ended'}
            <Age at={ended ?? started} />
            {ended === null ? '' : 'ago'}
        </span>
    )
}
