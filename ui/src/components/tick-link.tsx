import { Link } from '@tanstack/react-router'

import { Tip } from '@/components/tip'
import { tickRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/** `tick:N`, opening the tick's page: what it decided and why. Cut to fit its cell, it is whole on hover. */
export function TickLink({ id, className }: { id: number; className?: string }) {
    return (
        <Tip fact={tickRef(id)} mono whenCut>
            <Link
                to="/workspace/ticks/$id"
                params={{ id: String(id) }}
                className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
            >
                {tickRef(id)}
            </Link>
        </Tip>
    )
}
