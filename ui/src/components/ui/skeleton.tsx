// shadcn/ui Skeleton (components.json), ported by hand; see button.tsx. Only for a true first load (ui/DESIGN.md).
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

function Skeleton({ className, ...props }: ComponentProps<'div'>) {
    return (
        <div data-slot="skeleton" className={cn('animate-pulse rounded-sm bg-surface-raised', className)} {...props} />
    )
}

export { Skeleton }
