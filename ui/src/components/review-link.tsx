import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { reviewRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/**
 * `review:N`, opening the review's page: its findings on the diff, the shadow PR review canopy keeps (D114). With
 * `children`, those in its place, where a name says more than the id would (a persona among a request's reviews).
 */
export function ReviewLink({ id, className, children }: { id: number; className?: string; children?: ReactNode }) {
    return (
        <Link
            to="/pull-requests/reviews/$id"
            params={{ id: String(id) }}
            className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
        >
            {children ?? reviewRef(id)}
        </Link>
    )
}
