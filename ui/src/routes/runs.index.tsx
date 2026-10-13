import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { runsQuery } from '@/api/queries'
import { RUN_STATES, type RunState } from '@/api/types'
import { OrderToggle } from '@/components/order-toggle'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { TicketRunsTable } from '@/components/runs-table'
import { RunDot } from '@/components/status'
import { Skeleton } from '@/components/ui/skeleton'
import { ordered, useListOrder } from '@/lib/list-order'
import { byTicket } from '@/lib/run-state'
import { cn } from '@/lib/utils'

interface RunsSearch {
    state?: RunState | undefined
}

/**
 * Each ticket's runs as one row, by its latest run: running ones, then the ones that ended last. `?state=` keeps the
 * tickets whose latest run is in that state.
 */
export const Route = createFileRoute('/runs/')({
    // Typed search params: `?state=blocked` filters; anything else is dropped, never trusted. Return every key, even
    // when undefined: the router merges this over the raw search, so an omitted key would keep the raw value.
    validateSearch: (search: Record<string, unknown>): RunsSearch => ({
        state: RUN_STATES.find((s) => s === search['state']),
    }),
    component: RunsPage,
})

function RunsPage() {
    const { state } = Route.useSearch()
    const { data } = useQuery(runsQuery)
    const groups = data === undefined ? undefined : byTicket(data)
    const shown = state === undefined ? groups : groups?.filter((g) => g.latest.state === state)
    const order = useListOrder('runs')
    return (
        <>
            <PageHeader title="Runs">
                Each ticket's latest run, running ones first, then the ones that ended last: what it worked on, what it
                said, and what it cost. A ticket's earlier runs open under it.
            </PageHeader>
            <Panel>
                <PanelHeader label="By state">
                    <span className="flex items-center gap-3">
                        <nav aria-label="Filter by state" className="flex items-center gap-1">
                            <FilterLink search={{ state: undefined }}>all</FilterLink>
                            {RUN_STATES.map((s) => (
                                <FilterLink key={s} search={{ state: s }}>
                                    <RunDot state={s} />
                                    {s}
                                </FilterLink>
                            ))}
                        </nav>
                        {shown !== undefined && shown.length > 1 && <OrderToggle list="runs" />}
                    </span>
                </PanelHeader>
                {shown === undefined ? (
                    <div className="flex min-h-72 flex-col gap-2 p-3">
                        <Skeleton className="h-4 w-2/3" />
                        <Skeleton className="h-4 w-1/2" />
                    </div>
                ) : shown.length === 0 ? (
                    <Placeholder>{state ? `no ${state} runs` : 'no runs yet'}</Placeholder>
                ) : (
                    <TicketRunsTable groups={ordered('runs', order, shown)} />
                )}
            </Panel>
        </>
    )
}

/** A filter chip, selected when it matches the validated search: an unknown `?state=` selects `all`. */
function FilterLink({ search, children }: { search: RunsSearch; children: ReactNode }) {
    const { state } = Route.useSearch()
    return (
        <Link
            to="/runs"
            search={search}
            data-selected={search.state === state}
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
