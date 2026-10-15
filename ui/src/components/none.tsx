import { cn } from '@/lib/utils'

/**
 * What a field or a cell holds when it has no value: `none`, muted, so it never reads as a value, in its place's own
 * type. With a `reason`, why, after a colon (`none: canopy only reviews it`); `brief` keeps the reason for hover, in a
 * column too narrow for it. One phrase per concept: `NO_TICKET` in `src/lib/words.ts` for a PR canopy only reviews.
 */
export function None({ reason, brief = false, className }: { reason?: string; brief?: boolean; className?: string }) {
    const said = reason === undefined ? 'none' : `none: ${reason}`
    return (
        <span className={cn('text-muted-foreground', className)} title={brief ? said : undefined}>
            {brief ? 'none' : said}
        </span>
    )
}
