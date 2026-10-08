// shadcn/ui Skeleton (components.json), ported by hand; see button.tsx. Only for a true first load (ui/DESIGN.md).
// A light passes over it (`animate-shimmer`) where shadcn's pulses.
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

function Skeleton({ className, ...props }: ComponentProps<'div'>) {
    return (
        <div
            data-slot="skeleton"
            className={cn(
                'animate-shimmer rounded-sm bg-surface-raised',
                'bg-linear-to-r from-surface-raised via-border to-surface-raised',
                className,
            )}
            {...props}
        />
    )
}

export { Skeleton }
