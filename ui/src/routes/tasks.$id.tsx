import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { taskQuery } from '@/api/queries'
import type { TaskDetail } from '@/api/types'
import { Age } from '@/components/age'
import { Attachments } from '@/components/attachments'
import { ListPanel } from '@/components/list-panel'
import { Notice } from '@/components/notice'
import { Empty, PageHeader, Panel, PanelLoading, PanelScroll } from '@/components/panel'
import { TaskLeft } from '@/components/task-left'
import { TaskReportPanel } from '@/components/task-report'
import { TaskRunRow } from '@/components/task-row'
import { TaskStory } from '@/components/task-story'
import { ordered, useListOrder } from '@/lib/list-order'
import { taskRef } from '@/lib/refs'
import { RUN_TEXT } from '@/lib/run-state'
import { TASK_LOOK, taskTitle } from '@/lib/tasks'
import { cn } from '@/lib/utils'

// What every task's page shows, on its title's hover: its description is where the task stands.
const HELP =
    'A task you handed canopy: your instruction and its conversation, the report its latest run left, and what its ' +
    'runs left behind.'

/**
 * One task (DESIGN §36), as one story: the operator's instruction heads its conversation, which runs on through what
 * its runs said and the operator's replies, with the question waiting on them marked; then the report its latest run
 * left, the page's main content; then what its runs left (the branch, each pushed commit, the draft PR, the tickets),
 * and the runs themselves.
 */
export const Route = createFileRoute('/tasks/$id')({
    component: TaskPage,
})

function TaskPage() {
    const { id } = Route.useParams()
    // A task's id is a whole number; anything else names no task, and is never sent to the server as one.
    const number = /^[1-9]\d*$/u.test(id) ? Number(id) : undefined
    const query = useQuery({ ...taskQuery(number ?? 0), enabled: number !== undefined })
    const { data, error } = query
    if (number === undefined || (error instanceof ApiError && (error.status === 404 || error.status === 409))) {
        return (
            <>
                <PageHeader title={taskRef(id)} />
                <Panel>
                    {/* A task canopy has no record of is missing, and says why; a refusal is a Notice. */}
                    {error instanceof ApiError && error.status === 409 ? (
                        <Notice error={error} className="p-3" />
                    ) : (
                        <Empty size="panel">{`canopy has no ${taskRef(id)}`}</Empty>
                    )}
                </Panel>
            </>
        )
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader title={taskRef(number)} />
                <Panel>
                    <PanelLoading query={query} rows={1} className="min-h-72" />
                </Panel>
            </>
        )
    }
    // Each task its own page, so what one held (a thread's scroll) is never another's.
    return <Task key={data.task.id} detail={data} />
}

function Task({ detail }: { detail: TaskDetail }) {
    const { task, runs, tickets } = detail
    const look = TASK_LOOK[task.standing]
    const runsOrder = useListOrder('task-runs')
    return (
        <>
            <PageHeader title={taskRef(task.id)} subject={taskTitle(task.text)} help={HELP}>
                {/* Where it stands first, in its state's color, as a chore's page says how it is doing. */}
                <span className={RUN_TEXT[look.state]}>{look.word}</span>
                {/* Stopped, it says when once; stopped while its run still works, it says so after the rest. */}
                {task.stopped_at !== null && task.standing === 'stopped' && (
                    <>
                        {' '}
                        <Age at={task.stopped_at} variant="ago" />
                    </>
                )}
                {` · ${runs.length === 1 ? '1 run' : `${runs.length} runs`} · submitted `}
                <Age at={task.submitted_at} variant="ago" />
                {task.stopped_at !== null && task.standing !== 'stopped' && (
                    <>
                        {' · stopped '}
                        <Age at={task.stopped_at} variant="ago" />
                    </>
                )}
            </PageHeader>
            {/* One story, then what came of it: the narrow order is the reading order. Wide, the report, the page's
                main content, takes the second column beside the story and what the task left. */}
            <div
                className={cn(
                    'stagger flex flex-col gap-6',
                    '2xl:grid 2xl:grid-cols-[minmax(0,36rem)_minmax(0,1fr)] 2xl:items-start',
                    '2xl:grid-rows-[auto_auto_1fr]',
                )}
            >
                <Panel className="2xl:col-start-1 2xl:row-start-1" data-testid="task-conversation">
                    <TaskStory detail={detail} />
                    {/* What you attached for its runs to read; your text and replies say what to do with it (§22). */}
                    <Attachments
                        subject={{ kind: 'task', id: task.id }}
                        attachments={detail.attachments}
                        closed={task.stopped_at !== null}
                        className="border-t"
                    />
                </Panel>
                <TaskReportPanel task={task} runs={runs} className="2xl:col-start-2 2xl:row-span-3 2xl:row-start-1" />
                <TaskLeft task={task} runs={runs} tickets={tickets} className="2xl:col-start-1 2xl:row-start-2" />
                <ListPanel
                    label="Runs"
                    count={runs.length}
                    list="task-runs"
                    className="2xl:col-start-1 2xl:row-start-3"
                    data-testid="task-runs"
                >
                    <PanelScroll label="Runs">
                        <ul className="divide-y">
                            {ordered('task-runs', runsOrder, runs).map((run) => (
                                <TaskRunRow key={run.id} task={task.id} run={run} />
                            ))}
                        </ul>
                    </PanelScroll>
                </ListPanel>
            </div>
        </>
    )
}
