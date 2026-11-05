import { Link } from '@tanstack/react-router'

import { Tip } from '@/components/tip'
import { epicRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/** `epic:N`, opening the epic's page: its breakdown beside its members, its conversation, and its plan runs. */
export function EpicLink({ id, className }: { id: number; className?: string }) {
    return (
        <Tip fact={epicRef(id)} mono whenCut>
            <Link
                to="/epics/$id"
                params={{ id: String(id) }}
                className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
            >
                {epicRef(id)}
            </Link>
        </Tip>
    )
}
