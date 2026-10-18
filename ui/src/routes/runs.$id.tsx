import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { runMemoryQuery, runQuery, runTranscriptQuery } from '@/api/queries'
import type { Run } from '@/api/types'
import { Age } from '@/components/age'
import { Copyable, CopyablePath } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { Field, Fields } from '@/components/fields'
import { MemoryRows } from '@/components/memory'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { RichText } from '@/components/rich-text'
import { RunDoing } from '@/components/run-doing'
import { Chip, RunDot, Word } from '@/components/status'
import { TicketField } from '@/components/ticket-field'
import { Timestamp } from '@/components/timestamp'
import { TranscriptPanel } from '@/components/transcript'
import { runDescription } from '@/lib/descriptions'
import { runRef } from '@/lib/refs'
import { RUN_TEXT } from '@/lib/run-state'
import { tickId } from '@/lib/ticks'
import { readNothingText } from '@/lib/memory'
import { RUN_TOKENS_TITLE, runTokens } from '@/lib/transcript'
import { cn } from '@/lib/utils'
import { runKind } from '@/lib/words'
import { None } from '@/components/none'

// What every run's page shows, on its title's hover: its description is the run's state.
const HELP =
    "What the worker did, from its session's events in the run's log: its text, each tool call with its input and " +
    'output, and what each model call cost.'

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
    const query = useQuery(runQuery(id))
    const { data, error } = query
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
                    <PanelLoading query={query} rows={1} className="min-h-72" />
                </Panel>
            </>
        )
    }
    return (
        <>
            <PageHeader
                title={runRef(data.id)}
                subject={data.ticket_title}
                help={HELP}
                chips={data.private && <Chip>private</Chip>}
            >
                {runDescription(data)}
            </PageHeader>
            <div className="stagger flex flex-col gap-6">
                <RunPanel run={data} />
                <TranscriptPanel transcript={transcript} running={data.state === 'running'} />
                <RunMemoryPanel id={data.id} />
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
    return (
        <Panel>
            <PanelHeader label="Run">
                <span className={cn('flex items-center gap-1.5 font-mono text-xs', RUN_TEXT[run.state])}>
                    <RunDot state={run.state} />
                    <Word word={run.status} />
                </span>
            </PanelHeader>
            <Fields>
                {/* Private is the page's chip, beside its title: said once. */}
                <TicketField ticketKey={run.ticket_key} title={run.ticket_title} kind={runKind(run)} />
                <Field label="branch" mono>
                    {run.branch === null ? <None /> : <Copyable text={run.branch} label="branch" />}
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
                {run.activity && (
                    <Field label="last call">
                        <RunDoing activity={run.activity} />
                    </Field>
                )}
                <Field label="summary">{run.summary ? <RichText text={run.summary} /> : <None />}</Field>
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
                    <span title={RUN_TOKENS_TITLE}>{runTokens(run.new_tokens, run.peak_context)}</span>
                </Field>
                {run.worktrees.length > 0 && (
                    <Field label="worktrees" mono>
                        <span className="flex flex-wrap gap-x-4">
                            {run.worktrees.map((path) => (
                                <CopyablePath key={path} path={path} label="worktree path" />
                            ))}
                        </span>
                    </Field>
                )}
                <Field label="log" mono>
                    <CopyablePath path={run.log_path} label="log path">
                        <span title="the worker's stdout and stderr: yours alone">{run.log_path}</span>
                    </CopyablePath>
                </Field>
            </Fields>
        </Panel>
    )
}

/**
 * What the run wrote and read of agent memory (DESIGN §28), and what it had refused; only for a run rendered while a
 * tier was on. A run rendered while recording read `none, recording only`: nothing was served, which is not an empty
 * digest.
 */
function RunMemoryPanel({ id }: { id: number }) {
    const { data } = useQuery(runMemoryQuery(id))
    const rendered = data?.rendered ?? null
    if (data === undefined || rendered === null) {
        return null
    }
    const served = rendered.ticket_notes === 'use' || rendered.lessons === 'use'
    return (
        <Panel data-testid="run-memory">
            <PanelHeader label="Memory">
                <span className="readout text-xs text-muted-foreground">
                    ticket notes {words(rendered.ticket_notes)}, lessons {words(rendered.lessons)}
                </span>
            </PanelHeader>
            <h3 className="px-3 pt-2 panel-label">Wrote</h3>
            {data.wrote.length === 0 ? <Empty>none</Empty> : <MemoryRows entries={data.wrote} ownRun={id} />}
            <h3 className="border-t px-3 pt-2 panel-label">Read</h3>
            {data.read.length === 0 ? <Empty>{readNothingText(served)}</Empty> : <MemoryRows entries={data.read} />}
            {data.refused.length > 0 && (
                <>
                    <h3 className="border-t px-3 pt-2 panel-label">Refused</h3>
                    <ul className="flex flex-col gap-1 px-3 py-2 text-xs" data-testid="memory-refused">
                        {data.refused.map((r, i) => (
                            <li key={i}>
                                <span className="font-mono">
                                    {r.field}
                                    {r.key === null ? '' : ` ${r.key}`}
                                </span>
                                : {r.why}
                            </li>
                        ))}
                    </ul>
                </>
            )}
        </Panel>
    )
}

/** A tier's mode for a run, in the CLI's words. */
function words(mode: 'off' | 'record' | 'use'): string {
    return mode === 'use' ? 'in use' : mode === 'record' ? 'recording' : 'off'
}
