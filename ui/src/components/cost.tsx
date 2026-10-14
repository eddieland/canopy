import { costText } from '@/lib/cost-total'
import { cn } from '@/lib/utils'

/** A cost in dollars as a readout, `$0.42`, or a dash when nothing reported one, which says so on hover. */
export function Cost({ usd, className }: { usd: number | null; className?: string }) {
    return (
        <span className={cn('readout', className)} title={usd === null ? 'none reported' : undefined}>
            {costText(usd)}
        </span>
    )
}
