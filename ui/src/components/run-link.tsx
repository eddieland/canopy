import { Link } from '@tanstack/react-router'

import { Glance } from '@/components/glance'
import { RunGlance } from '@/components/ref-glances'
import { runRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/**
 * `run:N`, opening the run's page: what it did, and its session's transcript. Hovered or focused, a card shows it at
 * a glance, its reference whole.
 */
export function RunLink({ id, className }: { id: number; className?: string }) {
    return (
        <Glance card={<RunGlance id={id} />} testId="run-card" align="start" side="right">
            <Link
                to="/workspace/runs/$id"
                params={{ id: String(id) }}
                className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
            >
                {runRef(id)}
            </Link>
        </Glance>
    )
}
