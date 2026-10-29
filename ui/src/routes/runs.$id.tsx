import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { loopQuery, runMemoryQuery, runQuery, runTranscriptQuery } from '@/api/queries'
import type { Run, Transcript } from '@/api/types'
import { Copyable, CopyablePath } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { EndedOnField } from '@/components/ended-on'
import { WroteFeedbackPlan } from '@/components/feedback-plan-card'
import { Field, Fields } from '@/components/fields'
import { PersonaField } from '@/components/persona-field'
import { FoldPanel } from '@/components/fold-panel'
import { MemoryKinds } from '@/components/memory'
import { ModelsField } from '@/components/models-field'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { PromptPanel } from '@/components/prompt-panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { RichText } from '@/components/rich-text'
import { RunCardView } from '@/components/run-card'
import { RunDoing } from '@/components/run-doing'
import { Chip } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { RunOutputPanel } from '@/components/raw-output'
import { TranscriptPanel } from '@/components/transcript'
import { WhenField } from '@/components/when-field'
import { useTranscriptView } from '@/hooks/use-transcript-view'
import { runDescription } from '@/lib/descriptions'
import { runRef } from '@/lib/refs'
import { tickId } from '@/lib/ticks'
import { readNothingText } from '@/lib/memory'
import { RUN_TOKENS_TITLE, runTokens } from '@/lib/transcript'
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
    // The Run panel shows a transcript row as the context chart does, so the page holds how the transcript is shown.
    const view = useTranscriptView()
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
                {/* Its state, kind, and ticket, each said here alone: the ticket's key opens it. */}
                {runDescription(data)} · <TicketLink ticketKey={data.ticket_key} className="align-baseline" />
            </PageHeader>
            <div className="stagger flex flex-col gap-6">
                <RunPanel run={data} transcript={transcript} onShow={view.show} />
                <TranscriptPanel transcript={transcript} running={data.state === 'running'} page="run" view={view} />
                <PromptPanel transcript={transcript} />
                <RunOutputPanel id={data.id} />
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

/**
 * The run's facts, in the order every identity panel of a run, tick, or chore run keeps (ui/DESIGN.md, "A detail page
 * has one skeleton"): its answer, what came of it (for a feedback plan run, the plan it wrote, pointing at the PR's
 * page where it is approved), when, what it spent, then where its files are. Its state, kind, ticket, and title are
 * the page's header, so none is said here again.
 */
function RunPanel({
    run,
    transcript,
    onShow,
}: {
    run: Run
    transcript: Transcript | undefined
    onShow: (i: number) => void
}) {
    return (
        <Panel>
            <PanelHeader label="Run" />
            <Fields>
                <Field label="summary">{run.summary ? <RichText text={run.summary} /> : <None />}</Field>
                <EndedOnField status={run.status} transcript={transcript} onShow={onShow} />
                {run.feedback_plan !== null && (
                    <Field label="wrote" mono>
                        <WroteFeedbackPlan plan={run.feedback_plan} />
                    </Field>
                )}
                {run.card !== null && (
                    <Field label="card">
                        <RunCardView card={run.card} running={run.ended_at === null} />
                    </Field>
                )}
                {run.activity && (
                    <Field label="last call">
                        <RunDoing activity={run.activity} />
                    </Field>
                )}
                {run.prs.length > 0 && (
                    <Field label="pull requests" mono>
                        <span className="flex flex-wrap gap-x-4">
                            {run.prs.map((pr) => (
                                <PullRequestLink key={pr} url={pr} className="text-sm" />
                            ))}
                        </span>
                    </Field>
                )}
                <WhenField started={run.started_at} ended={run.ended_at} />
                <Field label="spent" mono>
                    <Cost usd={run.cost_usd} />
                    <span title={RUN_TOKENS_TITLE}>{runTokens(run.new_tokens, run.peak_context)}</span>
                </Field>
                <PersonaField persona={run.persona} digest={run.persona_digest} />
                {run.models !== null && <ModelsField models={run.models} asked={run.model} />}
                <Field label="branch" mono>
                    {run.branch === null ? <None /> : <Copyable text={run.branch} label="branch" />}
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
 * tier was on. It arrives folded: its header counts what it wrote and read, each tier's mode for the run on hover, and
 * `Show memory` opens the rows, grouped by kind. A run rendered while recording read `none, recording only`: nothing
 * was served, which is not an empty digest.
 */
function RunMemoryPanel({ id }: { id: number }) {
    const { data } = useQuery(runMemoryQuery(id))
    // Each tier's mode now, so a memory in force under a tier that only records reads `recorded` in its rows.
    const tiers = useQuery(loopQuery).data?.memory
    const modes = tiers ? { ticket_notes: tiers.ticket_notes.mode, lessons: tiers.lessons.mode } : undefined
    const rendered = data?.rendered ?? null
    if (data === undefined || rendered === null) {
        return null
    }
    const served = rendered.ticket_notes === 'use' || rendered.lessons === 'use'
    const tiersNow = `ticket notes: ${words(rendered.ticket_notes)}, lessons: ${words(rendered.lessons)}`
    const said = [
        `wrote ${data.wrote.length === 0 ? 'none' : data.wrote.length}`,
        `read ${data.read.length === 0 ? readNothingText(served) : data.read.length}`,
        ...(data.refused.length > 0 ? [`refused ${data.refused.length}`] : []),
    ].join(' · ')
    return (
        <FoldPanel
            label="Memory"
            what="memory"
            readout={
                <span className="readout text-xs text-muted-foreground" title={tiersNow} data-testid="run-memory-said">
                    {said}
                    <span className="sr-only">; {tiersNow}</span>
                </span>
            }
            data-testid="run-memory"
        >
            <h3 className="px-3 pt-2 panel-label">Wrote</h3>
            {data.wrote.length === 0 ? (
                <Empty>none</Empty>
            ) : (
                <MemoryKinds entries={data.wrote} ownRun={id} modes={modes} />
            )}
            <h3 className="border-t px-3 pt-2 panel-label">Read</h3>
            {data.read.length === 0 ? (
                <Empty>{readNothingText(served)}</Empty>
            ) : (
                <MemoryKinds entries={data.read} ownRun={id} cited={data} modes={modes} />
            )}
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
        </FoldPanel>
    )
}

/** A tier's mode for a run, in the words the header's readout and each tier's band use. */
function words(mode: 'off' | 'record' | 'use'): string {
    return mode === 'use' ? 'in use' : mode === 'record' ? 'recording' : 'off'
}
