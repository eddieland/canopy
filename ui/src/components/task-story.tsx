import type { TaskDetail, TaskRun } from '@/api/types'
import { Age } from '@/components/age'
import { Conversation } from '@/components/conversation'
import { Cost } from '@/components/cost'
import { OrderToggle } from '@/components/order-toggle'
import { PanelHeader, ThreadScroll } from '@/components/panel'
import { ReplyForm } from '@/components/reply-form'
import { RunDot } from '@/components/status'
import { TaskActions } from '@/components/task-actions'
import { TaskRunLink } from '@/components/task-link'
import { ordered, useListOrder } from '@/lib/list-order'
import { messageRef, taskRef } from '@/lib/refs'
import { waits } from '@/lib/tasks'
import { cn } from '@/lib/utils'

/**
 * A task's story (DESIGN §36), inside its Conversation panel: the operator's instruction at its oldest end, in their
 * own words, then what its runs said and the operator's replies, in the operator's order, ending on the run working it
 * now, as a ticket's does. The question waiting on the operator wears its chip, and the panel's foot answers it: the
 * reply form, then the task's stop.
 */
export function TaskStory({ detail }: { detail: TaskDetail }) {
    const { task, messages, runs } = detail
    const order = useListOrder('conversation')
    const working = runs.at(-1)?.status === 'running' ? runs.at(-1) : undefined
    const now = working && <WorkingNow task={task.id} run={working} />
    return (
        <>
            <PanelHeader label="Conversation">
                <span className="flex items-center gap-2">
                    {messages.length > 0 && <OrderToggle list="conversation" />}
                    <span className="readout text-xs text-muted-foreground">{messages.length + 1}</span>
                </span>
            </PanelHeader>
            <ThreadScroll key={`thread-${task.id}`} label="Conversation" end={order === 'oldest' ? 'bottom' : 'top'}>
                {order === 'newest' && now}
                <Conversation
                    messages={ordered('conversation', order, messages)}
                    task={task.id}
                    waiting={task.question_id ?? null}
                    instruction={{
                        ref: taskRef(task.id),
                        at: task.submitted_at,
                        body: task.text,
                        channel: task.channel,
                    }}
                    newestFirst={order === 'newest'}
                />
                {order === 'oldest' && now}
            </ThreadScroll>
            <TaskAnswer detail={detail} running={working?.id ?? null} />
        </>
    )
}

/** The run working the task now, on the worker's side at the thread's newest end: as a chat shows someone typing. */
function WorkingNow({ task, run }: { task: number; run: TaskRun }) {
    return (
        <p
            className="flex w-full max-w-2xl items-center gap-2 px-3 pb-3 font-mono text-xs text-muted-foreground"
            data-testid="working-now"
            aria-live="polite"
        >
            <RunDot state="running" />
            <span className="text-status-running">working now</span>
            <TaskRunLink task={task} run={run.id} />
            <span className="ml-auto flex shrink-0 items-center gap-3">
                <Cost usd={run.cost_usd} />
                <Age variant="span" started={run.started_at} ended={null} />
            </span>
        </p>
    )
}

/**
 * Where the task is answered, at its conversation's foot as a ticket's is: the reply form, then its stop, under a
 * hairline, so the reply is the first stop the keyboard reaches after the conversation and Stop never stands between
 * them. While a question waits, the form sits on what waits on the operator's tint, under a line naming the message it
 * asks in. A stopped task takes no reply, so it has no form, and its stop only what is still left to end.
 */
function TaskAnswer({ detail, running }: { detail: TaskDetail; running: number | null }) {
    const { task } = detail
    const question = waits(task) ? task.question_id : null
    // The run that asked, which the band names as a message's head does, opening its page.
    const asker = detail.messages.find((message) => message.id === question)?.task_run_id ?? null
    return (
        <>
            {/* One element whether a question waits or not, so the form keeps what it said as its reply clears it. */}
            {task.stopped_at === null && (
                <div
                    role={question === null ? undefined : 'region'}
                    aria-label={question === null ? undefined : 'A question waiting on you'}
                    className={cn(question !== null && 'border-t border-status-blocked/40 bg-status-blocked/8')}
                >
                    {question !== null && (
                        <p className="px-3 pt-3 text-xs">
                            <span className="font-medium text-status-blocked">Waiting on you: </span>
                            {asker === null ? 'its run' : <TaskRunLink task={task.id} run={asker} />} asked a question
                            in {messageRef(question)}.
                        </p>
                    )}
                    <ReplyForm
                        key={`reply-${task.id}`}
                        target={{ kind: 'task', id: task.id }}
                        waiting={question}
                        className={cn(question !== null && 'border-t-0')}
                    />
                </div>
            )}
            <TaskActions key={`actions-${task.id}`} task={task} running={running} />
        </>
    )
}
