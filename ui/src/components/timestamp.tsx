import { stamp } from '@/lib/time'
import { cn } from '@/lib/utils'

/** A moment as a short local readout, `Oct 8 10:30`, with the ISO time the journal keeps on hover. */
export function Timestamp({ at, className }: { at: string; className?: string }) {
    return (
        <time dateTime={at} title={at} className={cn('readout text-xs whitespace-nowrap', className)}>
            {stamp(at)}
        </time>
    )
}
