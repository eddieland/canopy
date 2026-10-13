import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { tickDetailQuery, tickTranscriptQuery } from '@/api/queries'
import type { TickDetail, Transcript } from '@/api/types'
import { Age } from '@/components/age'
import { Decisions } from '@/components/decisions'
import { OrderToggle } from '@/components/order-toggle'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { RichText } from '@/components/rich-text'
import { Chip } from '@/components/status'
import { TickOutputPanel } from '@/components/tick-output'
import { TranscriptPanel } from '@/components/transcript'
import { Skeleton } from '@/components/ui/skeleton'
import { ordered, useListOrder } from '@/lib/list-order'
import { localTime } from '@/lib/time'
import { TICK_TONE, tickId } from '@/lib/ticks'
import { cn } from '@/lib/utils'

/** One tick: the decisions it recorded, the overseer's transcript, and its output as written. */
export const Route = createFileRoute('/ticks/$id')({
    component: TickPage,
})

function TickPage() {
    const { id } = Route.useParams()
    const parsed = tickId(id)
    if (parsed === null) return <NoTick title={`tick ${id}`}>not a tick: a tick's id is a positive number</NoTick>
    return <Loaded id={parsed} />
}

function Loaded({ id }: { id: number }) {
    const { data, error } = useQuery(tickDetailQuery(id))
    const { data: transcript } = useQuery(tickTranscriptQuery(id))
    if (error instanceof ApiError && error.status === 404) return <NoTick title={`tick ${id}`}>{error.message}</NoTick>
    if (data === undefined) {
        return (
            <>
                <PageHeader title={`tick ${id}`} />
                <Panel className="min-h-72 p-3">
                    <Skeleton className="h-4 w-1/2" />
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
                <Placeholder className="min-h-40">{children}</Placeholder>
            </Panel>
        </>
    )
}

function Tick({ detail, transcript }: { detail: TickDetail; transcript: Transcript | undefined }) {
    const { tick, decisions, output_path: output } = detail
    const decisionsOrder = useListOrder('tick-decisions')
    return (
        <>
            <PageHeader title={`tick ${tick.id}`} chips={tick.dry_run && <Chip>dry run</Chip>}>
                What the overseer decided in this tick, and why, as{' '}
                <code className="font-mono text-xs">canopy decisions {tick.id}</code> prints it. Attention items and
                refusals are the harness's. Under them, the overseer's session: what it read and ran to decide; and
                under that, its output as written, stderr included.
            </PageHeader>
            <div className="stagger flex flex-col gap-6">
                <Panel>
                    <PanelHeader label="Tick">
                        <span className={cn('font-mono text-xs', TICK_TONE[tick.status] ?? 'text-muted-foreground')}>
                            {tick.status}
                        </span>
                    </PanelHeader>
                    <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 p-3 text-sm">
                        <dt className="panel-label self-center">started</dt>
                        <dd className="flex items-center gap-2 font-mono text-xs">
                            <span title={localTime(tick.started_at)}>{tick.started_at}</span>
                            <Age at={tick.started_at} />
                        </dd>
                        <dt className="panel-label self-center">ended</dt>
                        <dd className="font-mono text-xs">{tick.ended_at ?? 'still running'}</dd>
                        <dt className="panel-label">summary</dt>
                        <dd>
                            {tick.summary ? <RichText text={tick.summary} /> : <span className="text-sm">none</span>}
                        </dd>
                        <dt className="panel-label self-center">overseer</dt>
                        <dd className="font-mono text-xs">
                            {tick.session_id ? `session ${tick.session_id}` : 'no session reported'}
                            {tick.cost_usd === null ? '' : `  $${tick.cost_usd.toFixed(2)}`}
                        </dd>
                        <dt className="panel-label self-center">output</dt>
                        <dd
                            className="font-mono text-xs break-all"
                            title="the overseer's stdout and stderr: yours alone"
                        >
                            {output ?? 'none kept'}
                        </dd>
                    </dl>
                </Panel>
                <Panel>
                    <PanelHeader label="Decisions">
                        <span className="flex items-center gap-2">
                            {decisions.length > 1 && <OrderToggle list="tick-decisions" />}
                            <span className="readout text-xs text-muted-foreground">{decisions.length}</span>
                        </span>
                    </PanelHeader>
                    {decisions.length === 0 ? (
                        <Placeholder className="min-h-20">none</Placeholder>
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
