import { Link } from '@tanstack/react-router'

import { runRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/** `run:N`, opening the run's page: what it did, and its session's transcript. */
export function RunLink({ id, className }: { id: number; className?: string }) {
    return (
        <Link
            to="/workspace/runs/$id"
            params={{ id: String(id) }}
            className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
        >
            {runRef(id)}
        </Link>
    )
}
