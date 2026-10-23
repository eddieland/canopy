import { Link } from '@tanstack/react-router'

import { taskRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/** `task:N`, opening the task's page: its instruction and conversation, its report, and what it left. */
export function TaskLink({ id, className }: { id: number; className?: string }) {
    return (
        <Link
            to="/tasks/$id"
            params={{ id: String(id) }}
            className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
        >
            {taskRef(id)}
        </Link>
    )
}
