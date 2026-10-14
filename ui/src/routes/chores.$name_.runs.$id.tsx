import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { choreRunQuery, choreRunTranscriptQuery } from '@/api/queries'
import type { ChoreRunDetail } from '@/api/types'
import { Age } from '@/components/age'
import { ChoreFindingRow } from '@/components/chore-finding'
import { ChoreLink } from '@/components/chore-link'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { RichText } from '@/components/rich-text'
import { RunDot } from '@/components/status'
import { TranscriptPanel } from '@/components/transcript'
import { Skeleton } from '@/components/ui/skeleton'
import { RUN_TEXT } from '@/lib/run-state'
import { tickId } from '@/lib/ticks'
import { localTime } from '@/lib/time'
import { tokenCount } from '@/lib/transcript'
import { cn } from '@/lib/utils'

/** One chore run: how it ended, the whole of what it reported, and its session's transcript. */
export const Route = createFileRoute('/chores/$name_/runs/$id')({
    component: ChoreRunPage,
})

function ChoreRunPage() {
    const { name, id } = Route.useParams()
    const title = `chore:${name} #${id}`
    // A chore run's id is a positive number, as a run's is.
    const parsed = tickId(id)
    if (parsed === null) {
        return (
            <NoRun name={name} title={title}>
                not a chore run: its id is a positive number
            </NoRun>
        )
    }
    return <Loaded name={name} id={parsed} />
}

function Loaded({ name, id }: { name: string; id: number }) {
    const { data, error } = useQuery(choreRunQuery(name, id))
    // Read beside the run, not after it: the page waits on the slower of the two, not on both in turn.
    const { data: transcript } = useQuery(choreRunTranscriptQuery(name, id))
    const title = `chore:${name} #${id}`
    if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        return (
            <NoRun name={name} title={title}>
                {error.message}
            </NoRun>
        )
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader parents={<ChoreCrumb name={name} />} title={title} />
                <Panel className="min-h-72 p-3">
                    <Skeleton className="h-4 w-1/2" />
                </Panel>
            </>
        )
    }
    return (
        <>
            <PageHeader parents={<ChoreCrumb name={name} />} title={title}>
                What the chore&apos;s agent did, from its session&apos;s events in the run&apos;s log: its text, each
                tool call with its input and output, and what each model call cost.
            </PageHeader>
            <div className="stagger flex flex-col gap-6">
                <RunPanel detail={data} />
                {data.findings.length > 0 && (
                    <Panel data-testid="chore-run-findings">
                        <PanelHeader label="Findings">
                            <span className="readout text-xs text-muted-foreground">{data.findings.length}</span>
                        </PanelHeader>
                        <ul className="divide-y">
                            {data.findings.map((finding) => (
                                <ChoreFindingRow key={finding.id} finding={finding} />
                            ))}
                        </ul>
                    </Panel>
                )}
                <TranscriptPanel transcript={transcript} running={data.run.state === 'running'} />
            </div>
        </>
    )
}

function NoRun({ name, title, children }: { name: string; title: string; children: string }) {
    return (
        <>
            <PageHeader parents={<ChoreCrumb name={name} />} title={title} />
            <Panel>
                <Placeholder className="min-h-40">{children}</Placeholder>
            </Panel>
        </>
    )
}

function ChoreCrumb({ name }: { name: string }) {
    return (
        <Link to="/chores/$name" params={{ name }} activeOptions={{ exact: true }}>
            chore:{name}
        </Link>
    )
}

function RunPanel({ detail }: { detail: ChoreRunDetail }) {
    const { run } = detail
    return (
        <Panel>
            <PanelHeader label="Run">
                <span className={cn('flex items-center gap-1.5 font-mono text-xs', RUN_TEXT[run.state])}>
                    <RunDot state={run.state} />
                    {run.status}
                </span>
            </PanelHeader>
            <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 p-3 text-sm">
                <Field label="chore">
                    <ChoreLink name={detail.chore} />
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
                {detail.note && <Field label="harness">{detail.note}</Field>}
                <Field label="summary">{detail.summary ? <RichText text={detail.summary} /> : 'none'}</Field>
                <Field label="spent" mono>
                    {run.cost_usd === null ? 'none reported' : `$${run.cost_usd.toFixed(2)}`}
                    {run.tokens === null ? '' : `, ${tokenCount(run.tokens)} tokens`}
                </Field>
                <Field label="log" mono>
                    <span title="the chore's stdout and stderr: yours alone">{run.log_path}</span>
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
