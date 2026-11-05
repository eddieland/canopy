import { Link } from '@tanstack/react-router'

import { Tip } from '@/components/tip'
import { runRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/** `run:N`, opening the run's page: what it did, and its session's transcript. Cut to fit, it is whole on hover. */
export function RunLink({ id, className }: { id: number; className?: string }) {
    return (
        <Tip fact={runRef(id)} mono whenCut>
            <Link
                to="/workspace/runs/$id"
                params={{ id: String(id) }}
                className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
            >
                {runRef(id)}
            </Link>
        </Tip>
    )
}
