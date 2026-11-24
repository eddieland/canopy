import { Link } from '@tanstack/react-router'

import { Glance } from '@/components/glance'
import { TickGlance } from '@/components/ref-glances'
import { tickRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/**
 * `tick:N`, opening the tick's page: what it decided and why. Hovered or focused, a card shows it at a glance, its
 * reference whole.
 */
export function TickLink({ id, className }: { id: number; className?: string }) {
    return (
        <Glance card={<TickGlance id={id} />} testId="tick-glance" align="start">
            <Link
                to="/workspace/ticks/$id"
                params={{ id: String(id) }}
                className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
            >
                {tickRef(id)}
            </Link>
        </Glance>
    )
}
