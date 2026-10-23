import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { taskQuery, taskRunQuery, taskRunTranscriptQuery } from '@/api/queries'
import type { TaskRunDetail, Transcript } from '@/api/types'
import { Copyable, CopyablePath } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { EndedOnField } from '@/components/ended-on'
import { Field, Fields } from '@/components/fields'
import { ModelsField } from '@/components/models-field'
import { None } from '@/components/none'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { PromptPanel } from '@/components/prompt-panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { RichText } from '@/components/rich-text'
import { TaskLink } from '@/components/task-link'
import { TicketLink } from '@/components/ticket-link'
import { Tip } from '@/components/tip'
import { TranscriptPanel } from '@/components/transcript'
import { WhenField } from '@/components/when-field'
import { useTranscriptView } from '@/hooks/use-transcript-view'
import { taskRunDescription } from '@/lib/descriptions'
import { taskRunRef } from '@/lib/refs'
import { shortSha } from '@/lib/reviews'
import { taskTitle } from '@/lib/tasks'
import { tickId } from '@/lib/ticks'
import { RUN_TOKENS_TITLE, runTokens } from '@/lib/transcript'

// What every task run's page shows, on its title's hover: its description is the run's state.
const HELP =
    "What the task's worker did, from its session's events in the run's log: its text, each tool call with its input " +
    'and output, and what each model call cost.'

/** One run of a task (DESIGN §36): how it ended, the whole of what it said, and its session's transcript. */
export const Route = createFileRoute('/tasks/$id_/runs/$run')({
    component: TaskRunPage,
})

function TaskRunPage() {
    const { id, run } = Route.useParams()
    const title = taskRunRef(id, run)
    // A task's id and a run's are positive numbers; anything else names no run, and is never sent as one.
    const task = tickId(id)
    const parsed = tickId(run)
    if (task === null || parsed === null) {
        return (
            <NoRun task={task} title={title}>
                not a task run: its task and its id are positive numbers
            </NoRun>
        )
    }
    return <Loaded task={task} run={parsed} />
}

function Loaded({ task, run }: { task: number; run: number }) {
    const query = useQuery(taskRunQuery(task, run))
    const { data, error } = query
    // Read beside the run, not after it: the page waits on the slower of the two, not on both in turn.
    const { data: transcript } = useQuery(taskRunTranscriptQuery(task, run))
    // The task's text names the page, as a chore's title does its run's; its page has most often read it already.
    const parent = useQuery(taskQuery(task))
    const detail = parent.data
    // The Run panel shows a transcript row as the context chart does, so the page holds how the transcript is shown.
    const view = useTranscriptView()
    const title = taskRunRef(task, run)
    if (error instanceof ApiError && error.status === 404) {
        return (
            <NoRun task={task} title={title}>
                {error.message}
            </NoRun>
        )
    }
    // Held until the task is read too, so its title never moves the header once drawn; a failed read leaves it out.
    if (data === undefined || parent.isPending) {
        return (
            <>
                <PageHeader parents={<TaskLink id={task} />} title={title} />
                <Panel>
                    <PanelLoading query={query} rows={1} className="min-h-72" />
                </Panel>
            </>
        )
    }
    return (
        <>
            <PageHeader
                parents={<TaskLink id={task} />}
                title={title}
                subject={detail === undefined ? null : taskTitle(detail.task.text)}
                help={HELP}
            >
                {taskRunDescription(data.run)}
            </PageHeader>
            <div className="stagger flex flex-col gap-6">
                <RunPanel detail={data} transcript={transcript} onShow={view.show} />
                <TranscriptPanel
                    transcript={transcript}
                    running={data.run.state === 'running'}
                    page="task-run"
                    view={view}
                />
                <PromptPanel transcript={transcript} />
            </div>
        </>
    )
}

function NoRun({ task, title, children }: { task: number | null; title: string; children: string }) {
    return (
        <>
            <PageHeader parents={task === null ? undefined : <TaskLink id={task} />} title={title} />
            <Panel>
                <Empty size="panel">{children}</Empty>
            </Panel>
        </>
    )
}

/**
 * The task run's facts, in the order a run's and a chore run's keep (ui/DESIGN.md, the detail skeleton): its answer
 * and what came of it, when, what it spent, then its branch and log. Its state is the header's, its task the trail's,
 * so neither is said here.
 */
function RunPanel({
    detail,
    transcript,
    onShow,
}: {
    detail: TaskRunDetail
    transcript: Transcript | undefined
    onShow: (i: number) => void
}) {
    const { run } = detail
    return (
        <Panel>
            <PanelHeader label="Run" />
            <Fields>
                <Field label="summary">{detail.summary ? <RichText text={detail.summary} /> : <None />}</Field>
                {detail.question && (
                    <Field label="question">
                        <RichText text={detail.question} />
                    </Field>
                )}
                <EndedOnField status={run.status} transcript={transcript} onShow={onShow} />
                {run.prs.length > 0 && (
                    <Field label="pull requests" mono>
                        <span className="flex flex-wrap gap-x-4">
                            {run.prs.map((pr) => (
                                <PullRequestLink key={pr} url={pr} className="text-sm" />
                            ))}
                        </span>
                    </Field>
                )}
                {detail.note && <Field label="harness">{detail.note}</Field>}
                {detail.tickets.length > 0 && (
                    <Field label="tickets" mono>
                        <span className="flex flex-wrap gap-x-4">
                            {detail.tickets.map((ticket) => (
                                <TicketLink key={ticket.key} ticketKey={ticket.key} />
                            ))}
                        </span>
                    </Field>
                )}
                <WhenField started={run.started_at} ended={run.ended_at} />
                <Field label="spent" mono>
                    <Cost usd={run.cost_usd} />
                    <span title={RUN_TOKENS_TITLE}>{runTokens(run.new_tokens, run.peak_context)}</span>
                </Field>
                <ModelsField models={detail.models} />
                <Field label="branch" mono>
                    <Copyable text={run.branch} label="branch" />
                </Field>
                <Field label="commit" mono>
                    {run.head === null ? (
                        <None reason="nothing pushed" />
                    ) : (
                        <Copyable text={run.head} label="commit">
                            <Tip fact={run.head} mono>
                                <span className="readout">{shortSha(run.head)}</span>
                            </Tip>
                        </Copyable>
                    )}
                </Field>
                <Field label="log" mono>
                    <CopyablePath path={run.log_path} label="log path">
                        <span title="the worker's stdout and stderr: yours alone">{run.log_path}</span>
                    </CopyablePath>
                </Field>
            </Fields>
        </Panel>
    )
}
