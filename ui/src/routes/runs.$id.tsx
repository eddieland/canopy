import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { ExternalLink } from 'lucide-react'
import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { runQuery, runTranscriptQuery } from '@/api/queries'
import type { Run } from '@/api/types'
import { Age } from '@/components/age'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { RichText } from '@/components/rich-text'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TranscriptPanel } from '@/components/transcript'
import { Skeleton } from '@/components/ui/skeleton'
import { RUN_TEXT } from '@/lib/run-state'
import { tickId } from '@/lib/ticks'
import { localTime } from '@/lib/time'
import { tokenCount } from '@/lib/transcript'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/runs/$id')({
    component: RunPage,
})

function RunPage() {
    const { id } = Route.useParams()
    // A run's id is a positive number, as a tick's is.
    const parsed = tickId(id)
    if (parsed === null) return <NoRun title={`run:${id}`}>not a run: a run's id is a positive number</NoRun>
    return <Loaded id={parsed} />
}

function Loaded({ id }: { id: number }) {
    const { data, error } = useQuery(runQuery(id))
    // Read beside the run, not after it: the page waits on the slower of the two, not on both in turn.
    const { data: transcript } = useQuery(runTranscriptQuery(id))
    if (error instanceof ApiError && error.status === 404) return <NoRun title={`run:${id}`}>{error.message}</NoRun>
    if (data === undefined) {
        return (
            <>
                <PageHeader label="Run" title={`run:${id}`} />
                <Panel className="min-h-72 p-3">
                    <Skeleton className="h-4 w-1/2" />
                </Panel>
            </>
        )
    }
    return (
        <>
            <PageHeader label={data.private ? 'Run, private' : 'Run'} title={`run:${data.id}`}>
                What the worker did, from its session's events in the run's log: its text, each tool call with its input
                and output, and what each model call cost.
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
            <PageHeader label="Run" title={title} />
            <Panel>
                <Placeholder className="min-h-40">{children}</Placeholder>
            </Panel>
        </>
    )
}

function RunPanel({ run }: { run: Run }) {
    return (
        <Panel>
            <PanelHeader label="Run">
                <span className={cn('flex items-center gap-1.5 font-mono text-xs', RUN_TEXT[run.state])}>
                    <RunDot state={run.state} />
                    {run.status}
                </span>
            </PanelHeader>
            <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 p-3 text-sm">
                <Field label="ticket">
                    <span className="flex items-center gap-2">
                        <TicketLink ticketKey={run.ticket_key} />
                        <Chip word={run.kind} />
                        {run.private && <Chip>private</Chip>}
                        {run.ticket_title !== null && (
                            <span className="min-w-0 truncate" title={run.ticket_title}>
                                {run.ticket_title}
                            </span>
                        )}
                    </span>
                </Field>
                <Field label="branch" mono>
                    {run.branch ?? 'none'}
                </Field>
                <Field label="started" mono>
                    <span className="flex items-center gap-2">
                        <span title={localTime(run.started_at)}>{run.started_at}</span>
                        <Age at={run.started_at} />
                    </span>
                </Field>
                <Field label="ended" mono>
                    {run.ended_at ?? 'still running'}
                </Field>
                <Field label="summary">{run.summary ? <RichText text={run.summary} /> : 'none'}</Field>
                {run.prs.length > 0 && (
                    <Field label="pull requests" mono>
                        <span className="flex flex-wrap gap-x-4">
                            {run.prs.map((pr) => (
                                <a
                                    key={pr}
                                    href={pr}
                                    target="_blank"
                                    rel="noreferrer noopener"
                                    className={cn(
                                        'inline-flex items-center gap-1 text-accent',
                                        'underline-offset-4 hover:underline',
                                    )}
                                >
                                    {pr.replace(/^https:\/\//, '')}
                                    <ExternalLink className="size-3" />
                                </a>
                            ))}
                        </span>
                    </Field>
                )}
                <Field label="spent" mono>
                    {run.cost_usd === null ? 'none reported' : `$${run.cost_usd.toFixed(2)}`}
                    {run.tokens === null ? '' : `, ${tokenCount(run.tokens)} tokens`}
                </Field>
                {run.worktrees.length > 0 && (
                    <Field label="worktrees" mono>
                        {run.worktrees.join('  ')}
                    </Field>
                )}
                <Field label="log" mono>
                    <span title="the worker's stdout and stderr: yours alone">{run.log_path}</span>
                </Field>
            </dl>
        </Panel>
    )
}

function Field({ label, mono = false, children }: { label: string; mono?: boolean; children: ReactNode }) {
    return (
        <>
            <dt className="panel-label self-center">{label}</dt>
            <dd className={cn('min-w-0 break-words', mono ? 'font-mono text-xs break-all' : 'text-sm')}>{children}</dd>
        </>
    )
}
