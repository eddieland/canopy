import { None } from '@/components/none'
import { UNREAD } from '@/lib/models'
import { cn } from '@/lib/utils'

/**
 * The name of a spend's row of runs no session named a model for, in muted sans as no id (`DESIGN.md`, A model):
 * `unread` for those whose sessions canopy has yet to read, else `none: no session named one`.
 */
export function UnnamedModel({ unread, className }: { unread: boolean; className?: string }) {
    return unread ? (
        <span className={cn('font-sans text-muted-foreground', className)}>{UNREAD}</span>
    ) : (
        <None reason="no session named one" className={cn('font-sans', className)} />
    )
}
