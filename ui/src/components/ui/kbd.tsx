// shadcn/ui Kbd, Vega style (components.json), ported by hand because the registry was unreachable. Its style classes
// are inlined and its tooltip and per-theme overrides dropped: a keycap takes its colors from where it sits.
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** One key, drawn as a keycap. */
export function Kbd({ className, ...props }: ComponentProps<'kbd'>) {
    return (
        <kbd
            data-slot="kbd"
            className={cn(
                'pointer-events-none inline-flex h-5 w-fit min-w-5 items-center justify-center gap-1 rounded-sm px-1',
                'bg-muted font-sans text-xs font-medium text-muted-foreground select-none',
                "[&_svg:not([class*='size-'])]:size-3",
                className,
            )}
            {...props}
        />
    )
}

/** Keys pressed together, side by side. */
export function KbdGroup({ className, ...props }: ComponentProps<'kbd'>) {
    return <kbd data-slot="kbd-group" className={cn('inline-flex items-center gap-1', className)} {...props} />
}
