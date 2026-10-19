import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { tickDetailQuery, tickTranscriptQuery } from '@/api/queries'
import type { TickDetail, Transcript } from '@/api/types'
import { Cost } from '@/components/cost'
import { Decisions } from '@/components/decisions'
import { Field, Fields } from '@/components/fields'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { RichText } from '@/components/rich-text'
import { Chip } from '@/components/status'
import { TickOutputPanel } from '@/components/raw-output'
import { TickSteps } from '@/components/tick-steps'
import { TranscriptPanel } from '@/components/transcript'
import { WhenField } from '@/components/when-field'
import { ordered, useListOrder } from '@/lib/list-order'
import { tickDescription } from '@/lib/descriptions'
import { tickRef } from '@/lib/refs'
import { tickId } from '@/lib/ticks'
import { RUN_TOKENS_TITLE, runTokens } from '@/lib/transcript'
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
    const query = useQuery(tickDetailQuery(id))
    const { data, error } = query
    const { data: transcript } = useQuery(tickTranscriptQuery(id))
    if (error instanceof ApiError && error.status === 404) {
        return <NoTick title={tickRef(id)}>{error.message}</NoTick>
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader title={tickRef(id)} />
                <Panel>
                    <PanelLoading query={query} rows={1} className="min-h-72" />
                </Panel>
            </>
        )
    }
    return <Tick detail={data} transcript={transcript} />
}

/** What every tick's page shows, on its title's hover: its description is the tick's state. */
function help(id: number): string {
    return (
        `What the overseer decided in this tick, and why, as canopy decisions ${id} prints it. Attention items and ` +
        "refusals are the harness's. Under them, the overseer's session: what it read and ran to decide; and under " +
        'that, its output as written, stderr included.'
    )
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
    const { tick, decisions, output_path: output, previous_id: previous, next_id: next } = detail
    const decisionsOrder = useListOrder('tick-decisions')
    return (
        <>
            <PageHeader
                title={tickRef(tick.id)}
                help={help(tick.id)}
                chips={tick.dry_run && <Chip>dry run</Chip>}
                controls={<TickSteps previous={previous} next={next} />}
            >
                {tickDescription(tick, decisions.length)}
            </PageHeader>
            <div className="stagger flex flex-col gap-6">
                {/* Its facts in the order a run's and a chore run's keep (ui/DESIGN.md, the detail skeleton): its
                    state is the header's, its session the transcript's, its output's path the Output panel's. */}
                <Panel>
                    <PanelHeader label="Tick" />
                    <Fields>
                        <Field label="summary">{tick.summary ? <RichText text={tick.summary} /> : <None />}</Field>
                        <WhenField started={tick.started_at} ended={tick.ended_at} />
                        <Field label="spent" mono>
                            <Cost usd={tick.cost_usd} />
                            <span title={RUN_TOKENS_TITLE}>{runTokens(tick.new_tokens, tick.peak_context)}</span>
                        </Field>
                        <Field
                            label="canopy"
                            mono
                            title="the version of canopy that ran this tick and recorded its decisions"
                        >
                            {tick.canopy_version ?? <None />}
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
                <TranscriptPanel transcript={transcript} running={tick.status === 'running'} page="tick" />
                <TickOutputPanel id={tick.id} path={output} />
            </div>
        </>
    )
}
