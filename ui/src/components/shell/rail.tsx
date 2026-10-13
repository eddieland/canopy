import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { metaQuery, runsQuery, spendQuery } from '@/api/queries'
import type { SpendWindow } from '@/api/types'
import { Age } from '@/components/age'
import { RunDot } from '@/components/status'
import { Kbd } from '@/components/ui/kbd'
import { Skeleton } from '@/components/ui/skeleton'
import { railRuns } from '@/lib/run-state'

// Rows the rail lists before `+N more`: with the nav and the spend, four keep the sticky part within an 800px window.
const RAIL_RUNS = 4

/**
 * Under the nav, on every page: the runs working now, those waiting on the operator's answer first, each opening its
 * page. The runs come whole from the stream, so a row appears when a run starts and leaves when it ends.
 */
export function RailWorking() {
    const runs = useQuery(runsQuery).data
    const { shown, more } = railRuns(runs ?? [], RAIL_RUNS)
    return (
        <RailSection label="Working" testId="rail-working" count={runs === undefined ? undefined : shown.length + more}>
            {runs === undefined ? (
                <Skeleton className="mx-2.5 h-8" />
            ) : shown.length === 0 ? (
                <p className="px-2.5 text-xs text-muted-foreground">nothing running</p>
            ) : (
                <ul className="flex flex-col gap-0.5">
                    {shown.map((run) => (
                        <li key={run.id}>
                            <Link
                                to="/runs/$id"
                                params={{ id: String(run.id) }}
                                title={`run:${run.id} ${run.kind}`}
                                className="flex flex-col gap-0.5 rounded-sm px-2.5 py-1.5 hover:bg-surface-raised"
                                data-testid={`rail-run-${run.id}`}
                            >
                                <span className="flex items-center gap-2 font-mono text-xs">
                                    <RunDot state={run.state} />
                                    <span className="text-foreground">{run.ticket_key}</span>
                                    <span className="ml-auto">
                                        {run.state === 'blocked' ? (
                                            <span className="readout text-xs text-status-blocked">asks</span>
                                        ) : (
                                            <Age at={run.started_at} />
                                        )}
                                    </span>
                                </span>
                                <span className="truncate pl-4 text-xs text-muted-foreground">
                                    {run.ticket_title ?? run.kind}
                                </span>
                            </Link>
                        </li>
                    ))}
                    {more > 0 && (
                        <li>
                            <Link
                                to="/runs"
                                className="block px-2.5 py-1 font-mono text-xs text-accent hover:underline"
                            >
                                +{more} more
                            </Link>
                        </li>
                    )}
                </ul>
            )}
        </RailSection>
    )
}

/** Under the working runs: what the last 24 hours and the last 30 days cost, as the attention page's counters say. */
export function RailSpend() {
    const spend = useQuery(spendQuery).data
    return (
        <RailSection label="Spent" testId="rail-spend">
            <div className="grid grid-cols-2 gap-2 px-2.5">
                <Spent window={spend?.day} label="24h" />
                <Spent window={spend?.month} label="30d" />
            </div>
        </RailSection>
    )
}

/** The rail's foot: the search key and the version canopy serves. At the window's foot, or the page's when longer. */
export function RailFooter() {
    const meta = useQuery(metaQuery).data
    return (
        <div
            className="mx-2 flex flex-col gap-1.5 border-t px-2.5 py-3 text-[0.6875rem] text-muted-foreground"
            data-testid="rail-footer"
        >
            <span className="flex items-center gap-1.5">
                <Kbd>/</Kbd> search
            </span>
            <span className="readout min-h-4 truncate" title={meta?.version} data-testid="rail-version">
                {meta === undefined ? '' : `canopy ${meta.version}`}
            </span>
        </div>
    )
}

/** A block of the rail: a hairline above, a label, and what it holds. */
function RailSection({
    label,
    testId,
    count,
    children,
}: {
    label: string
    testId: string
    count?: number
    children: ReactNode
}) {
    return (
        <section aria-label={label} className="mx-2 mt-3 border-t pt-3" data-testid={testId}>
            <div className="flex items-center justify-between px-2.5 pb-1.5">
                <span className="panel-label text-[0.625rem]">{label}</span>
                {count !== undefined && <span className="readout text-[0.625rem] text-muted-foreground">{count}</span>}
            </div>
            {children}
        </section>
    )
}

/** One window's cost: a dash when nothing in it reported one. */
function Spent({ window, label }: { window: SpendWindow | undefined; label: string }) {
    const cost = window?.cost_usd ?? null
    return (
        <div className="flex flex-col">
            {window === undefined ? (
                <Skeleton className="h-5 w-14" />
            ) : (
                <span className="readout text-sm text-foreground" data-testid={`rail-spend-${label}`}>
                    {cost === null ? '–' : `$${cost.toFixed(2)}`}
                </span>
            )}
            <span className="text-[0.6875rem] text-muted-foreground">{label}</span>
        </div>
    )
}
