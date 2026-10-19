import { Clipped } from '@/components/tip'
import { cn } from '@/lib/utils'

/**
 * A ticket's title, as the overseer named it (DESIGN §7): one line in medium weight, so it reads as the row's name
 * beside the key and apart from what a run said, cut to fit with the whole in a `Tip` while it is cut. A ticket with
 * none yet says `untitled`, muted, so its cell is never blank.
 */
export function TicketTitle({ title, className }: { title: string | null; className?: string }) {
    if (title === null) {
        return <span className={cn('min-w-0 truncate text-sm text-muted-foreground', className)}>untitled</span>
    }
    return <Clipped text={title} className={cn('min-w-0 text-sm font-medium', className)} />
}
