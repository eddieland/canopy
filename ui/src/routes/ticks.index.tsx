import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ticksQuery } from '@/api/queries'
import type { Tick } from '@/api/types'
import { Ended } from '@/components/age'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { ListRow } from '@/components/rows'
import { Chip } from '@/components/status'
import { TickLink } from '@/components/tick-link'
import { ordered, useListOrder } from '@/lib/list-order'
import { rowLineFrom } from '@/lib/rows'
import { TICK_TONE } from '@/lib/ticks'
import { cn } from '@/lib/utils'

/** The latest ticks, newest first, as `canopy decisions` prints them. */
export const Route = createFileRoute('/ticks/')({
    component: TicksPage,
})

function TicksPage() {
    const { data } = useQuery(ticksQuery)
    const order = useListOrder('ticks')
    return (
        <>
            <PageHeader title="Ticks">
                The latest ticks, newest first: what each found, what its overseer cost, and how many decisions it
                recorded, as <code className="font-mono text-xs">canopy decisions</code> prints them.
            </PageHeader>
            <Panel>
                <PanelHeader label="Ticks">
                    <span className="flex items-center gap-2">
                        {data !== undefined && data.length > 1 && <OrderToggle list="ticks" />}
                        <span className="readout text-xs text-muted-foreground">{data?.length ?? ''}</span>
                    </span>
                </PanelHeader>
                {data === undefined ? (
                    <PanelSkeleton className="min-h-72" />
                ) : data.length === 0 ? (
                    <Empty size="panel">
                        no ticks yet: <code className="font-mono text-xs">canopy tick</code> runs one, and{' '}
                        <code className="font-mono text-xs">canopy loop</code> one after another
                    </Empty>
                ) : (
                    <ul className="stagger divide-y" data-testid="ticks">
                        {ordered('ticks', order, data).map((tick) => (
                            <Row key={tick.id} tick={tick} />
                        ))}
                    </ul>
                )}
            </Panel>
        </>
    )
}

function Row({ tick }: { tick: Tick }) {
    return (
        <ListRow kind="tick" data-testid={`tick-${tick.id}`}>
            <TickLink id={tick.id} />
            <span className="flex min-w-0 items-center gap-3">
                <span className={cn('font-mono text-xs', TICK_TONE[tick.status] ?? 'text-muted-foreground')}>
                    {tick.status}
                </span>
                {tick.dry_run && <Chip>dry run</Chip>}
            </span>
            <span className="readout text-right text-xs text-muted-foreground" data-testid="tick-decisions">
                {tick.decisions === 1 ? '1 decision' : `${tick.decisions} decisions`}
            </span>
            <span className="readout text-right text-xs text-muted-foreground">
                {tick.cost_usd === null ? '' : `$${tick.cost_usd.toFixed(2)}`}
            </span>
            <Ended started={tick.started_at} ended={tick.ended_at} />
            {tick.summary && <RichText text={tick.summary} lines={SUMMARY_LINES} className={rowLineFrom('state')} />}
        </ListRow>
    )
}
