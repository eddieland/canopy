import { Link } from '@tanstack/react-router'

import { taskRef, taskRunRef } from '@/lib/refs'
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

/** One run of a task, as `task:N#M`, opening its page: how it ended, the whole of what it said, and its session. */
export function TaskRunLink({ task, run, className }: { task: number; run: number; className?: string }) {
    return (
        <Link
            to="/tasks/$id/runs/$run"
            params={{ id: String(task), run: String(run) }}
            className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
        >
            {taskRunRef(task, run)}
        </Link>
    )
}
