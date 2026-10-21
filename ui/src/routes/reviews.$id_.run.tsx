import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { reviewQuery, reviewTranscriptQuery } from '@/api/queries'
import type { ReviewDetail, Transcript } from '@/api/types'
import { CopyablePath } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { EndedOnField } from '@/components/ended-on'
import { Field, Fields } from '@/components/fields'
import { ModelsField } from '@/components/models-field'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { PromptPanel } from '@/components/prompt-panel'
import { ReviewOutputPanel } from '@/components/raw-output'
import { TranscriptPanel } from '@/components/transcript'
import { WhenField } from '@/components/when-field'
import { useTranscriptView } from '@/hooks/use-transcript-view'
import { reviewDescription } from '@/lib/descriptions'
import { reviewRef } from '@/lib/refs'
import { tickId } from '@/lib/ticks'
import { RUN_TOKENS_TITLE, runTokens } from '@/lib/transcript'

// What every review run's page shows, on its title's hover: its description is the run's state.
const HELP =
    "What the reviewer did, from its session's events in the review's log: its text, each tool call with its input " +
    'and output, and what each model call cost. Its findings are on the review’s page.'

/**
 * A review's run on a page of its own: how it ended, what it spent, its log, its reviewer's transcript and prompt. The
 * review's page is its results, read far more often, so it links here from its `run` field rather than show this.
 */
export const Route = createFileRoute('/reviews/$id_/run')({
    component: ReviewRunPage,
})

function ReviewRunPage() {
    const { id } = Route.useParams()
    // A review run's id is a positive number, as a run's is.
    const parsed = tickId(id)
    if (parsed === null) {
        return <NoReview id={id}>not a review: its id is a positive number</NoReview>
    }
    return <Loaded id={parsed} />
}

function Loaded({ id }: { id: number }) {
    const query = useQuery(reviewQuery(id))
    const { data, error } = query
    // Read beside the review, not after it: the page waits on the slower of the two, not on both in turn.
    const { data: transcript } = useQuery(reviewTranscriptQuery(id))
    // The Run panel shows a transcript row as the context chart does, so the page holds how the transcript is shown.
    const view = useTranscriptView()
    if (error instanceof ApiError && error.status === 404) {
        return <NoReview id={id}>{error.message}</NoReview>
    }
    if (data === undefined) {
        return (
            <>
                <RunHeader id={id} />
                <Panel>
                    <PanelLoading query={query} rows={1} className="min-h-72" />
                </Panel>
            </>
        )
    }
    return (
        <>
            <RunHeader id={id} subject={data.ticket_title}>
                {reviewDescription(data.review)}
            </RunHeader>
            <div className="stagger flex flex-col gap-6">
                <RunPanel detail={data} transcript={transcript} onShow={view.show} />
                <TranscriptPanel
                    transcript={transcript}
                    running={data.review.state === 'running'}
                    page="review"
                    view={view}
                />
                <PromptPanel transcript={transcript} />
                <ReviewOutputPanel id={id} />
            </div>
        </>
    )
}

/** The page's header: under its review in the trail, as a ticket's plan is under the ticket. */
function RunHeader({ id, subject, children }: { id: number | string; subject?: string | null; children?: string }) {
    return (
        <PageHeader
            parents={
                <Link to="/reviews/$id" params={{ id: String(id) }} activeOptions={{ exact: true }}>
                    {reviewRef(id)}
                </Link>
            }
            title="Run"
            subject={subject}
            tab={`${reviewRef(id)} run`}
            help={HELP}
        >
            {children}
        </PageHeader>
    )
}

function NoReview({ id, children }: { id: string | number; children: string }) {
    return (
        <>
            <RunHeader id={id} />
            <Panel>
                <Empty size="panel">{children}</Empty>
            </Panel>
        </>
    )
}

/**
 * The review run's facts, in the order a run's and a chore run's keep (ui/DESIGN.md, the detail skeleton): what it
 * ended on, the harness's note, when, what it spent, then its log. Its state is the header's, and its summary,
 * verdict, and findings the review's page's, so none is said here.
 */
function RunPanel({
    detail,
    transcript,
    onShow,
}: {
    detail: ReviewDetail
    transcript: Transcript | undefined
    onShow: (i: number) => void
}) {
    const { review } = detail
    return (
        <Panel>
            <PanelHeader label="Run" />
            <Fields>
                <EndedOnField status={review.status} transcript={transcript} onShow={onShow} />
                {detail.note !== null && (
                    <Field label="harness">
                        <span className="text-status-failed">{detail.note}</span>
                    </Field>
                )}
                <WhenField started={review.started_at} ended={review.ended_at} />
                <Field label="spent" mono>
                    <Cost usd={review.cost_usd} />
                    <span title={RUN_TOKENS_TITLE}>{runTokens(detail.new_tokens, detail.peak_context)}</span>
                </Field>
                <ModelsField models={detail.models} />
                <Field label="log" mono>
                    <CopyablePath path={detail.log_path} label="log path">
                        <span title="the reviewer's stdout and stderr: yours alone">{detail.log_path}</span>
                    </CopyablePath>
                </Field>
            </Fields>
        </Panel>
    )
}
