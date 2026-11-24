import { Link } from '@tanstack/react-router'

import { Glance } from '@/components/glance'
import { TaskGlance, TaskRunGlance } from '@/components/ref-glances'
import { taskRef, taskRunRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/** `task:N`, opening the task's page: its instruction and conversation, its report, and what it left. */
export function TaskLink({ id, className }: { id: number; className?: string }) {
    return (
        <Glance card={<TaskGlance id={id} />} testId="task-card" align="start">
            <Link
                to="/tasks/$id"
                params={{ id: String(id) }}
                className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
            >
                {taskRef(id)}
            </Link>
        </Glance>
    )
}

/**
 * One run of a task, as `task:N#M`, opening its page: how it ended, the whole of what it said, and its session. Cut to
 * fit its cell, it is whole on hover.
 */
export function TaskRunLink({ task, run, className }: { task: number; run: number; className?: string }) {
    return (
        <Glance card={<TaskRunGlance task={task} run={run} />} testId="task-run-card" align="start">
            <Link
                to="/tasks/$id/runs/$run"
                params={{ id: String(task), run: String(run) }}
                className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
            >
                {taskRunRef(task, run)}
            </Link>
        </Glance>
    )
}
