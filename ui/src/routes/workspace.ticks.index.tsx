import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { idleTicksQuery, ticksQuery } from '@/api/queries'
import { Code } from '@/components/code'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { TickNow } from '@/components/tick-now'
import { TickRow } from '@/components/tick-row'
import { ordered, useListOrder } from '@/lib/list-order'
import { cn } from '@/lib/utils'

interface TicksSearch {
    // Only the live ticks the loop found idle: what the spend page's Ticks panel links.
    idle?: true | undefined
}

/**
 * The latest ticks, newest first, as `canopy decisions` prints them; `?idle=true` keeps the latest the loop found idle,
 * which the spend page's Ticks panel opens.
 */
export const Route = createFileRoute('/workspace/ticks/')({
    // Typed search params: anything but `true` reads as every tick.
    validateSearch: (search: Record<string, unknown>): TicksSearch => ({
        idle: search['idle'] === true || search['idle'] === 'true' ? true : undefined,
    }),
    component: TicksPage,
})

function TicksPage() {
    const { idle } = Route.useSearch()
    const { data } = useQuery(idle === true ? idleTicksQuery : ticksQuery)
    const order = useListOrder('ticks')
    return (
        <>
            <PageHeader title="Ticks">
                The latest ticks, newest first: what each found, what its overseer cost in dollars, tokens, and peak
                context, and how many decisions it recorded, as <Code>canopy decisions</Code> prints them.
            </PageHeader>
            <Panel>
                <PanelHeader label="Ticks">
                    <span className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
                        <nav aria-label="Filter ticks" className="flex items-center gap-1" data-testid="ticks-filter">
                            <FilterLink search={{ idle: undefined }} selected={idle !== true}>
                                all
                            </FilterLink>
                            <FilterLink search={{ idle: true }} selected={idle === true}>
                                idle
                            </FilterLink>
                        </nav>
                        {data !== undefined && data.length > 1 && <OrderToggle list="ticks" />}
                        <span className="readout text-xs text-muted-foreground">{data?.length ?? ''}</span>
                    </span>
                </PanelHeader>
                {data === undefined ? (
                    <PanelSkeleton className="min-h-72" />
                ) : data.length === 0 && idle === true ? (
                    <Empty size="panel">no idle ticks yet: the loop marks a tick idle when it started no work</Empty>
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

/** A filter chip, the runs page's look: the ticks page with `search`, marked when it is the one shown. */
function FilterLink({ search, selected, children }: { search: TicksSearch; selected: boolean; children: ReactNode }) {
    return (
        <Link
            to="/workspace/ticks"
            search={search}
            data-selected={selected}
            className={cn(
                'flex h-6 items-center gap-1.5 rounded-sm px-2 font-mono text-xs text-muted-foreground',
                'hover:bg-surface-raised hover:text-foreground',
                'data-[selected=true]:bg-accent/16 data-[selected=true]:text-foreground',
            )}
        >
            {children}
        </Link>
    )
}
