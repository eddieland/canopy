import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ticksQuery } from '@/api/queries'
import { Code } from '@/components/code'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { TickNow } from '@/components/tick-now'
import { TickRow } from '@/components/tick-row'
import { ordered, useListOrder } from '@/lib/list-order'

/** The latest ticks, newest first, as `canopy decisions` prints them. */
export const Route = createFileRoute('/workspace/ticks/')({
    component: TicksPage,
})

function TicksPage() {
    const { data } = useQuery(ticksQuery)
    const order = useListOrder('ticks')
    return (
        <>
            <PageHeader title="Ticks">
                The latest ticks, newest first: what each found, what its overseer cost in dollars, tokens, and peak
                context, and how many decisions it recorded, as <Code>canopy decisions</Code> prints them.
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
                        no ticks yet: the loop runs one every <Code>loop.interval_minutes</Code>, or now with{' '}
                        <TickNow inline />
                    </Empty>
                ) : (
                    <ul className="divide-y" data-testid="ticks">
                        {ordered('ticks', order, data).map((tick) => (
                            <TickRow key={tick.id} tick={tick} />
                        ))}
                    </ul>
                )}
            </Panel>
        </>
    )
}
