import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { choreRunQuery, choreRunTranscriptQuery } from '@/api/queries'
import type { ChoreRunDetail } from '@/api/types'
import { Age } from '@/components/age'
import { ChoreFindingRow } from '@/components/chore-finding'
import { ChoreLink } from '@/components/chore-link'
import { Cost } from '@/components/cost'
import { Field, Fields } from '@/components/fields'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { RichText } from '@/components/rich-text'
import { RunDot, Word } from '@/components/status'
import { Timestamp } from '@/components/timestamp'
import { TranscriptPanel } from '@/components/transcript'
import { choreRunDescription } from '@/lib/descriptions'
import { choreRef, choreRunRef } from '@/lib/refs'
import { RUN_TEXT } from '@/lib/run-state'
import { tickId } from '@/lib/ticks'
import { RUN_TOKENS_TITLE, runTokens } from '@/lib/transcript'
import { cn } from '@/lib/utils'
import { None } from '@/components/none'

// What every chore run's page shows, on its title's hover: its description is the run's state.
const HELP =
    "What the chore's agent did, from its session's events in the run's log: its text, each tool call with its input " +
    'and output, and what each model call cost.'

/** One chore run: how it ended, the whole of what it reported, and its session's transcript. */
export const Route = createFileRoute('/chores/$name_/runs/$id')({
    component: ChoreRunPage,
})

function ChoreRunPage() {
    const { name, id } = Route.useParams()
    const title = choreRunRef(name, id)
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
    const title = choreRunRef(name, id)
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
                <Panel>
                    <PanelSkeleton rows={1} className="min-h-72" />
                </Panel>
            </>
        )
    }
    return (
        <>
            <PageHeader parents={<ChoreCrumb name={name} />} title={title} help={HELP}>
                {choreRunDescription(data.run, data.findings.length)}
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
                <Empty size="panel">{children}</Empty>
            </Panel>
        </>
    )
}

function ChoreCrumb({ name }: { name: string }) {
    return (
        <Link to="/chores/$name" params={{ name }} activeOptions={{ exact: true }}>
            {choreRef(name)}
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
                    <Word word={run.status} />
                </span>
            </PanelHeader>
            <Fields>
                <Field label="chore">
                    <ChoreLink name={detail.chore} />
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
                {detail.note && <Field label="harness">{detail.note}</Field>}
                <Field label="summary">{detail.summary ? <RichText text={detail.summary} /> : <None />}</Field>
                <Field label="spent" mono>
                    <Cost usd={run.cost_usd} />
                    <span title={RUN_TOKENS_TITLE}>{runTokens(run.new_tokens, run.peak_context)}</span>
                </Field>
                <Field label="log" mono>
                    <span title="the chore's stdout and stderr: yours alone">{run.log_path}</span>
                </Field>
            </Fields>
        </Panel>
    )
}
