import { Link } from '@tanstack/react-router'

import { Glance } from '@/components/glance'
import { EpicGlance } from '@/components/ref-glances'
import { epicRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/** `epic:N`, opening the epic's page: its breakdown beside its members, its conversation, and its plan runs. */
export function EpicLink({ id, className }: { id: number; className?: string }) {
    return (
        <Glance card={<EpicGlance id={id} />} testId="epic-card" align="start" side="right">
            <Link
                to="/epics/$id"
                params={{ id: String(id) }}
                className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
            >
                {epicRef(id)}
            </Link>
        </Glance>
    )
}
