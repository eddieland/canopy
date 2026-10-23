import type { TaskRun, TaskSummary } from '@/api/types'
import { Age } from '@/components/age'
import { Copyable } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { LinkedText } from '@/components/linked-text'
import { PullRequestLink } from '@/components/pull-request-link'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { ListRow, RowLine } from '@/components/rows'
import { RunDot, Word } from '@/components/status'
import { TaskLink } from '@/components/task-link'
import { TicketTitle } from '@/components/ticket-title'
import { Clipped } from '@/components/tip'
import { taskRunRef } from '@/lib/refs'
import { rowLineFrom } from '@/lib/rows'
import { RUN_TEXT } from '@/lib/run-state'
import { TASK_LOOK, taskTitle } from '@/lib/tasks'
import { cn } from '@/lib/utils'

/**
 * A task in the tasks list: where it stands, in its run state's dot and color (`TASK_LOOK`), its id, opening its page,
 * its repository, the first line of its text, and when it was submitted; under its text, the first line of what its
 * latest run said, an agent's words, as text.
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
            <TaskLink id={task.id} />
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

/**
 * One run of a task on its page, in a run's columns there (`own-run`): its state, its reference (`task:4#5`, text
 * until a task's run has a page of its own), cost, and when; under them, what it said, the PRs it named, and its
 * session.
 */
export function TaskRunRow({ task, run }: { task: number; run: TaskRun }) {
    return (
        <ListRow kind="own-run" className="group/copy" data-testid={`task-run-${String(run.id)}`}>
            <span className={cn('flex items-center gap-1.5 font-mono text-xs', RUN_TEXT[run.state])}>
                <RunDot state={run.state} />
                <Word word={run.status} />
            </span>
            <span className="readout text-xs">{taskRunRef(task, run.id)}</span>
            <span className="text-right text-xs text-muted-foreground">
                <Cost usd={run.cost_usd} />
            </span>
            <Age variant="span" started={run.started_at} ended={run.ended_at ?? null} className="text-right" />
            {run.summary && <RichText text={run.summary} lines={SUMMARY_LINES} className={rowLineFrom('facts')} />}
            {(run.prs.length > 0 || run.session_id) && (
                <RowLine from="facts" className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs">
                    {run.prs.map((pr) => (
                        <PullRequestLink key={pr} url={pr} />
                    ))}
                    {run.session_id && (
                        <Copyable text={run.session_id} label="session id" reveal className="text-muted-foreground">
                            session {run.session_id}
                        </Copyable>
                    )}
                </RowLine>
            )}
        </ListRow>
    )
}
