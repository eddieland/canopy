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
