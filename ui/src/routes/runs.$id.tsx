import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { runQuery, runTranscriptQuery } from '@/api/queries'
import type { Run } from '@/api/types'
import { Age } from '@/components/age'
import { Copyable } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { Field, Fields } from '@/components/fields'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { RichText } from '@/components/rich-text'
import { Chip, RunDot, Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Timestamp } from '@/components/timestamp'
import { TranscriptPanel } from '@/components/transcript'
import { useWholePath } from '@/hooks/use-whole-path'
import { runRef } from '@/lib/refs'
import { RUN_TEXT } from '@/lib/run-state'
import { tickId } from '@/lib/ticks'
import { tokenCount } from '@/lib/transcript'
import { cn } from '@/lib/utils'

/** One run: what it worked on, how it ended, and its session's transcript. */
export const Route = createFileRoute('/runs/$id')({
    component: RunPage,
})

function RunPage() {
    const { id } = Route.useParams()
    // A run's id is a positive number, as a tick's is.
    const parsed = tickId(id)
    if (parsed === null) {
        return <NoRun title={runRef(id)}>not a run: a run&apos;s id is a positive number</NoRun>
    }
    return <Loaded id={parsed} />
}

function Loaded({ id }: { id: number }) {
    const { data, error } = useQuery(runQuery(id))
    // Read beside the run, not after it: the page waits on the slower of the two, not on both in turn.
    const { data: transcript } = useQuery(runTranscriptQuery(id))
    if (error instanceof ApiError && error.status === 404) {
        return <NoRun title={runRef(id)}>{error.message}</NoRun>
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader title={runRef(id)} />
                <Panel>
                    <PanelSkeleton rows={1} className="min-h-72" />
                </Panel>
            </>
        )
    }
    return (
        <>
            <PageHeader title={runRef(data.id)} chips={data.private && <Chip>private</Chip>}>
                What the worker did, from its session&apos;s events in the run&apos;s log: its text, each tool call with
                its input and output, and what each model call cost.
            </PageHeader>
            <div className="stagger flex flex-col gap-6">
                <RunPanel run={data} />
                <TranscriptPanel transcript={transcript} running={data.state === 'running'} />
            </div>
        </>
    )
}

function NoRun({ title, children }: { title: string; children: string }) {
    return (
        <>
            <PageHeader title={title} />
            <Panel>
                <Empty size="panel">{children}</Empty>
            </Panel>
        </>
    )
}

function RunPanel({ run }: { run: Run }) {
    const whole = useWholePath()
    return (
        <Panel>
            <PanelHeader label="Run">
                <span className={cn('flex items-center gap-1.5 font-mono text-xs', RUN_TEXT[run.state])}>
                    <RunDot state={run.state} />
                    <Word word={run.status} />
                </span>
            </PanelHeader>
            <Fields>
                <Field label="ticket">
                    <span className="flex items-center gap-2">
                        <TicketLink ticketKey={run.ticket_key} />
                        <Chip word={run.kind} />
                        {run.private && <Chip>private</Chip>}
                        <TicketTitle title={run.ticket_title} />
                    </span>
                </Field>
                <Field label="branch" mono>
                    {run.branch === null ? 'none' : <Copyable text={run.branch} label="branch" />}
                </Field>
                <Field label="started" mono>
                    <span className="flex items-baseline gap-2">
                        <Timestamp at={run.started_at} />
                        <Age at={run.started_at} variant="ago" />
                    </span>
                </Field>
                <Field label="ended" mono>
                    {run.ended_at === null ? 'still running' : <Timestamp at={run.ended_at} />}
                </Field>
                <Field label="summary">{run.summary ? <RichText text={run.summary} /> : 'none'}</Field>
                {run.prs.length > 0 && (
                    <Field label="pull requests" mono>
                        <span className="flex flex-wrap gap-x-4">
                            {run.prs.map((pr) => (
                                <PullRequestLink key={pr} url={pr} className="text-sm" />
                            ))}
                        </span>
                    </Field>
                )}
                <Field label="spent" mono>
                    <Cost usd={run.cost_usd} />
                    {run.tokens === null ? '' : `, ${tokenCount(run.tokens)} tokens`}
                </Field>
                {run.worktrees.length > 0 && (
                    <Field label="worktrees" mono>
                        <span className="flex flex-wrap gap-x-4">
                            {run.worktrees.map((path) => (
                                <Copyable key={path} text={whole(path)} label="worktree path">
                                    {path}
                                </Copyable>
                            ))}
                        </span>
                    </Field>
                )}
                <Field label="log" mono>
                    <Copyable text={whole(run.log_path)} label="log path">
                        <span title="the worker's stdout and stderr: yours alone">{run.log_path}</span>
                    </Copyable>
                </Field>
            </Fields>
        </Panel>
    )
}
