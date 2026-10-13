import { cn } from '@/lib/utils'

/**
 * A ticket's title, as the overseer named it (DESIGN §7): one line in medium weight, so it reads as the row's name
 * beside the key and apart from what a run said, cut to fit with the whole on hover. Nothing when it has none.
 */
export function TicketTitle({ title, className }: { title: string | null; className?: string }) {
    return (
        <span className={cn('min-w-0 truncate text-sm font-medium', className)} title={title ?? undefined}>
            {title}
        </span>
    )
}
