import { Link } from '@tanstack/react-router'

import { reviewRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/** `review:N`, opening the review's page: its findings on the diff, the shadow PR review canopy keeps (D114). */
export function ReviewLink({ id, className }: { id: number; className?: string }) {
    return (
        <Link
            to="/reviews/$id"
            params={{ id: String(id) }}
            className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
        >
            {reviewRef(id)}
        </Link>
    )
}
