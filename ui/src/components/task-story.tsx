import type { TaskDetail, TaskRun } from '@/api/types'
import { Age } from '@/components/age'
import { Conversation } from '@/components/conversation'
import { Copyable } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { OrderToggle } from '@/components/order-toggle'
import { PanelHeader, ThreadScroll } from '@/components/panel'
import { RunDot } from '@/components/status'
import { TaskRunLink } from '@/components/task-link'
import { ordered, useListOrder } from '@/lib/list-order'
import { messageRef, taskRef } from '@/lib/refs'
import { replyCommand, waits } from '@/lib/tasks'
import { cn } from '@/lib/utils'

/**
 * A task's story (DESIGN §36), inside its Conversation panel: the operator's instruction at its oldest end, in their
 * own words, then what its runs said and the operator's replies, in the operator's order, ending on the run working it
 * now, as a ticket's does. The question waiting on the operator wears its chip, and the panel's foot says how to answer
 * it: from the shell, `canopy reply task:N TEXT`, until the page has a reply box of its own.
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
            <ReplyFoot detail={detail} />
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
 * Where the reply box will be: how to answer the task from the shell. While a question waits, a band in what waits on
 * the operator's tint, naming the message it asks in; otherwise one muted line on what a reply does. A stopped task
 * takes no reply, so it has none.
 */
function ReplyFoot({ detail }: { detail: TaskDetail }) {
    const { task } = detail
    if (task.standing === 'stopped') {
        return null
    }
    const command = replyCommand(task.id)
    const waiting = waits(task) && task.question_id !== null
    return (
        <section
            aria-label={waiting ? 'A question waiting on you' : 'Reply'}
            data-testid="task-reply"
            className={cn(
                'flex flex-wrap items-center gap-x-1.5 gap-y-1 border-t px-3 py-2 text-xs',
                waiting ? 'border-status-blocked/40 bg-status-blocked/8' : 'text-muted-foreground',
            )}
        >
            {waiting ? (
                <span>
                    <span className="font-medium text-status-blocked">Waiting on you: </span>
                    its run asked a question in {messageRef(task.question_id ?? 0)}. Answer it from your shell:
                </span>
            ) : (
                <span>A reply queues its next run, on the same branch. Send one from your shell:</span>
            )}
            <Copyable text={command} label="reply command" className="font-mono text-foreground">
                {command} <span className="text-muted-foreground">TEXT</span>
            </Copyable>
        </section>
    )
}
