import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { choreRunQuery, choreRunTranscriptQuery } from '@/api/queries'
import type { ChoreRunDetail, Transcript } from '@/api/types'
import { ChoreFindingRow } from '@/components/chore-finding'
import { CopyablePath } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { EndedOnField } from '@/components/ended-on'
import { Field, Fields } from '@/components/fields'
import { ListPanel } from '@/components/list-panel'
import { Notice } from '@/components/notice'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { RichText } from '@/components/rich-text'
import { PromptPanel } from '@/components/prompt-panel'
import { TranscriptPanel } from '@/components/transcript'
import { WhenField } from '@/components/when-field'
import { useTranscriptView } from '@/hooks/use-transcript-view'
import { choreRunDescription } from '@/lib/descriptions'
import { choreRef, choreRunRef } from '@/lib/refs'
import { tickId } from '@/lib/ticks'
import { RUN_TOKENS_TITLE, runTokens } from '@/lib/transcript'
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
    const query = useQuery(choreRunQuery(name, id))
    const { data, error } = query
    // Read beside the run, not after it: the page waits on the slower of the two, not on both in turn.
    const { data: transcript } = useQuery(choreRunTranscriptQuery(name, id))
    // The Run panel shows a transcript row as the context chart does, so the page holds how the transcript is shown.
    const view = useTranscriptView()
    const title = choreRunRef(name, id)
    if (error instanceof ApiError && error.status === 404) {
        return (
            <NoRun name={name} title={title}>
                {error.message}
            </NoRun>
        )
    }
    if (error instanceof ApiError && error.status === 409) {
        return (
            <>
                <PageHeader parents={<ChoreCrumb name={name} />} title={title} />
                <Panel>
                    <Notice error={error} className="p-3" />
                </Panel>
            </>
        )
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader parents={<ChoreCrumb name={name} />} title={title} />
                <Panel>
                    <PanelLoading query={query} rows={1} className="min-h-72" />
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
                <RunPanel detail={data} transcript={transcript} onShow={view.show} />
                {/* Left out with none: the description counts them (`no findings`), so a `0` would say it twice. */}
                {data.findings.length > 0 && (
                    <ListPanel label="Findings" count={data.findings.length} data-testid="chore-run-findings">
                        <ul className="divide-y">
                            {data.findings.map((finding) => (
                                <ChoreFindingRow key={finding.id} finding={finding} />
                            ))}
                        </ul>
                    </ListPanel>
                )}
                <TranscriptPanel
                    transcript={transcript}
                    running={data.run.state === 'running'}
                    page="chore-run"
                    view={view}
                />
                <PromptPanel transcript={transcript} />
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

/**
 * The chore run's facts, in the order a run's and a tick's keep (ui/DESIGN.md, the detail skeleton): its answer, when,
 * what it spent, then its log. Its state and findings are the header's, its chore the trail's, so none is said here.
 */
function RunPanel({
    detail,
    transcript,
    onShow,
}: {
    detail: ChoreRunDetail
    transcript: Transcript | undefined
    onShow: (i: number) => void
}) {
    const { run } = detail
    return (
        <Panel>
            <PanelHeader label="Run" />
            <Fields>
                <Field label="summary">{detail.summary ? <RichText text={detail.summary} /> : <None />}</Field>
                <EndedOnField status={run.status} transcript={transcript} onShow={onShow} />
                {detail.note && <Field label="harness">{detail.note}</Field>}
                <WhenField started={run.started_at} ended={run.ended_at} />
                <Field label="spent" mono>
                    <Cost usd={run.cost_usd} />
                    <span title={RUN_TOKENS_TITLE}>{runTokens(run.new_tokens, run.peak_context)}</span>
                </Field>
                <Field label="log" mono>
                    <CopyablePath path={run.log_path} label="log path">
                        <span title="the chore's stdout and stderr: yours alone">{run.log_path}</span>
                    </CopyablePath>
                </Field>
            </Fields>
        </Panel>
    )
}
