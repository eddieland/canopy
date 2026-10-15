import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { tickDetailQuery, tickTranscriptQuery } from '@/api/queries'
import type { TickDetail, Transcript } from '@/api/types'
import { Age } from '@/components/age'
import { Copyable } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { Decisions } from '@/components/decisions'
import { Field, Fields } from '@/components/fields'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { RichText } from '@/components/rich-text'
import { Chip, RunDot, Word } from '@/components/status'
import { TickOutputPanel } from '@/components/tick-output'
import { Timestamp } from '@/components/timestamp'
import { TranscriptPanel } from '@/components/transcript'
import { ordered, useListOrder } from '@/lib/list-order'
import { tickRef } from '@/lib/refs'
import { RUN_TEXT } from '@/lib/run-state'
import { tickId, tickState } from '@/lib/ticks'
import { RUN_TOKENS_TITLE, runTokens } from '@/lib/transcript'
import { cn } from '@/lib/utils'
import { None } from '@/components/none'

/** One tick: the decisions it recorded, the overseer's transcript, and its output as written. */
export const Route = createFileRoute('/ticks/$id')({
    component: TickPage,
})

function TickPage() {
    const { id } = Route.useParams()
    const parsed = tickId(id)
    if (parsed === null) {
        return <NoTick title={tickRef(id)}>not a tick: a tick&apos;s id is a positive number</NoTick>
    }
    return <Loaded id={parsed} />
}

function Loaded({ id }: { id: number }) {
    const { data, error } = useQuery(tickDetailQuery(id))
    const { data: transcript } = useQuery(tickTranscriptQuery(id))
    if (error instanceof ApiError && error.status === 404) {
        return <NoTick title={tickRef(id)}>{error.message}</NoTick>
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader title={tickRef(id)} />
                <Panel>
                    <PanelSkeleton rows={1} className="min-h-72" />
                </Panel>
            </>
        )
    }
    return <Tick detail={data} transcript={transcript} />
}

function NoTick({ title, children }: { title: string; children: string }) {
    return (
        <>
            <PageHeader title={title} />
            <Panel>
                <Empty size="panel">{children}</Empty>
            </Panel>
        </>
    )
}

function Tick({ detail, transcript }: { detail: TickDetail; transcript: Transcript | undefined }) {
    const { tick, decisions, output_path: output } = detail
    const decisionsOrder = useListOrder('tick-decisions')
    return (
        <>
            <PageHeader title={tickRef(tick.id)} chips={tick.dry_run && <Chip>dry run</Chip>}>
                What the overseer decided in this tick, and why, as{' '}
                <code className="font-mono text-xs">canopy decisions {tick.id}</code> prints it. Attention items and
                refusals are the harness&apos;s. Under them, the overseer&apos;s session: what it read and ran to
                decide; and under that, its output as written, stderr included.
            </PageHeader>
            <div className="stagger flex flex-col gap-6">
                <Panel>
                    <PanelHeader label="Tick">
                        <span
                            className={cn(
                                'flex items-center gap-1.5 font-mono text-xs',
                                RUN_TEXT[tickState(tick.status)],
                            )}
                        >
                            <RunDot state={tickState(tick.status)} />
                            <Word word={tick.status} />
                        </span>
                    </PanelHeader>
                    <Fields>
                        <Field label="started" mono>
                            <span className="flex items-baseline gap-2">
                                <Timestamp at={tick.started_at} />
                                <Age at={tick.started_at} variant="ago" />
                            </span>
                        </Field>
                        <Field label="ended" mono>
                            {tick.ended_at === null ? 'still running' : <Timestamp at={tick.ended_at} />}
                        </Field>
                        <Field label="summary">{tick.summary ? <RichText text={tick.summary} /> : <None />}</Field>
                        <Field label="overseer" mono>
                            {tick.session_id ? (
                                <Copyable text={tick.session_id} label="session id">
                                    session {tick.session_id}
                                </Copyable>
                            ) : (
                                <None />
                            )}
                        </Field>
                        <Field label="spent" mono>
                            <Cost usd={tick.cost_usd} />
                            <span title={RUN_TOKENS_TITLE}>{runTokens(tick.new_tokens, tick.peak_context)}</span>
                        </Field>
                        <Field label="output" mono title="the overseer's stdout and stderr: yours alone">
                            {output ?? <None />}
                        </Field>
                    </Fields>
                </Panel>
                <Panel>
                    <PanelHeader label="Decisions">
                        <span className="flex items-center gap-2">
                            {decisions.length > 1 && <OrderToggle list="tick-decisions" />}
                            <span className="readout text-xs text-muted-foreground">{decisions.length}</span>
                        </span>
                    </PanelHeader>
                    {decisions.length === 0 ? (
                        <Empty>no decisions yet: its overseer has recorded none</Empty>
                    ) : (
                        <Decisions decisions={ordered('tick-decisions', decisionsOrder, decisions)} />
                    )}
                </Panel>
                <TranscriptPanel transcript={transcript} running={tick.status === 'running'} />
                <TickOutputPanel id={tick.id} path={output} running={tick.status === 'running'} />
            </div>
        </>
    )
}
