import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ticksQuery } from '@/api/queries'
import type { Tick } from '@/api/types'
import { Age } from '@/components/age'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { Chip } from '@/components/status'
import { TickLink } from '@/components/tick-link'
import { Skeleton } from '@/components/ui/skeleton'
import { TICK_TONE } from '@/lib/ticks'
import { cn } from '@/lib/utils'

/** The latest ticks, newest first, as `canopy decisions` prints them. */
export const Route = createFileRoute('/ticks/')({
    component: TicksPage,
})

function TicksPage() {
    const { data } = useQuery(ticksQuery)
    return (
        <>
            <PageHeader label="Overseer" title="Ticks">
                The latest ticks, newest first: what each found, what its overseer cost, and how many decisions it
                recorded, as <code className="font-mono text-xs">canopy decisions</code> prints them.
            </PageHeader>
            <Panel>
                <PanelHeader label="Ticks">
                    <span className="readout text-xs text-muted-foreground">{data?.length ?? ''}</span>
                </PanelHeader>
                {data === undefined ? (
                    <div className="flex min-h-72 flex-col gap-2 p-3">
                        <Skeleton className="h-4 w-2/3" />
                        <Skeleton className="h-4 w-1/2" />
                    </div>
                ) : data.length === 0 ? (
                    <Placeholder>no ticks yet</Placeholder>
                ) : (
                    <ul className="stagger divide-y" data-testid="ticks">
                        {data.map((tick) => (
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
        <li className="flex flex-col gap-1 px-3 py-2.5" data-testid={`tick-${tick.id}`}>
            <div className="flex items-center gap-3">
                <TickLink id={tick.id} className="w-20" />
                <span className={cn('w-32 font-mono text-xs', TICK_TONE[tick.status] ?? 'text-muted-foreground')}>
                    {tick.status}
                </span>
                {tick.dry_run && <Chip>dry run</Chip>}
                <span className="ml-auto flex items-center gap-4">
                    <span
                        className="readout w-24 text-right text-xs text-muted-foreground"
                        data-testid="tick-decisions"
                    >
                        {tick.decisions === 1 ? '1 decision' : `${tick.decisions} decisions`}
                    </span>
                    <span className="readout w-16 text-right text-xs text-muted-foreground">
                        {tick.cost_usd === null ? '' : `$${tick.cost_usd.toFixed(2)}`}
                    </span>
                    <span className="flex w-24 justify-end gap-1 text-xs text-muted-foreground">
                        {tick.ended_at === null ? 'for' : 'ended'}
                        <Age at={tick.ended_at ?? tick.started_at} />
                        {tick.ended_at === null ? '' : 'ago'}
                    </span>
                </span>
            </div>
            {tick.summary && <RichText text={tick.summary} lines={SUMMARY_LINES} className="pl-[6.75rem]" />}
        </li>
    )
}
