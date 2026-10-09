import { Link } from '@tanstack/react-router'

import { cn } from '@/lib/utils'

/** `tick N`, opening the tick's page: what it decided and why. */
export function TickLink({ id, className }: { id: number; className?: string }) {
    return (
        <Link
            to="/ticks/$id"
            params={{ id: String(id) }}
            className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
        >
            tick {id}
        </Link>
    )
}
