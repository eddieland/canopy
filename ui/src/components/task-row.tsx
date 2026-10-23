import type { TaskSummary } from '@/api/types'
import { Age } from '@/components/age'
import { LinkedText } from '@/components/linked-text'
import { ListRow, RowLine } from '@/components/rows'
import { RunDot } from '@/components/status'
import { TicketTitle } from '@/components/ticket-title'
import { Clipped } from '@/components/tip'
import { RUN_TEXT } from '@/lib/run-state'
import { TASK_LOOK, taskTitle } from '@/lib/tasks'
import { cn } from '@/lib/utils'

/**
 * A task in the tasks list: where it stands, in its run state's dot and color (`TASK_LOOK`), its id, its repository,
 * the first line of its text, and when it was submitted; under its text, the first line of what its latest run said,
 * an agent's words, as text. Its id is text until a task has a page of its own.
 */
export function TaskRow({ task }: { task: TaskSummary }) {
    const look = TASK_LOOK[task.standing]
    const said = task.latest?.summary?.split('\n', 1)[0] ?? ''
    return (
        <ListRow kind="task" data-testid={`task-${String(task.id)}`}>
            <span className={cn('flex items-center gap-1.5 font-mono text-xs whitespace-nowrap', RUN_TEXT[look.state])}>
                <RunDot state={look.state} />
                {look.word}
            </span>
            <span className="readout text-xs">task:{task.id}</span>
            <Clipped text={task.repo} mono className="text-xs text-muted-foreground" />
            <TicketTitle title={taskTitle(task.text)} />
            <Age at={task.submitted_at} variant="ago" className="text-right" />
            {said !== '' && (
                <RowLine from="title">
                    <Clipped text={said} className="block text-xs text-muted-foreground">
                        <LinkedText text={said} />
                    </Clipped>
                </RowLine>
            )}
        </ListRow>
    )
}
