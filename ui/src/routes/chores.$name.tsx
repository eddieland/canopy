import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { choreQuery } from '@/api/queries'
import type { ChoreDetail, ChoreRun, ChoreSpend, ChoreSpendWindow } from '@/api/types'
import { Ended } from '@/components/age'
import { ChoreFindingRow } from '@/components/chore-finding'
import { ChoreNotes } from '@/components/chore-notes'
import { Field, Fields } from '@/components/fields'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelScroll, PanelSkeleton } from '@/components/panel'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { ListRow, RowLine } from '@/components/rows'
import { Chip, RunDot } from '@/components/status'
import { choreLine, costText, runsText, windowText } from '@/lib/chores'
import { ordered, useListOrder } from '@/lib/list-order'
import { choreRef, choreRunRef } from '@/lib/refs'
import { rowLineFrom } from '@/lib/rows'
import { RUN_TEXT } from '@/lib/run-state'
import { useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

/** One chore: its schedule, its open findings, its recent runs, and the operator's notes to it. */
export const Route = createFileRoute('/chores/$name')({
    component: ChorePage,
})

function ChorePage() {
    const { name } = Route.useParams()
    const { data, error } = useQuery(choreQuery(name))
    if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        return (
            <>
                <PageHeader title={choreRef(name)} />
                <Panel>
                    <Empty size="panel">{error.message}</Empty>
                </Panel>
            </>
        )
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader title={choreRef(name)} />
                <Panel>
                    <PanelSkeleton rows={1} className="min-h-72" />
                </Panel>
            </>
        )
    }
    return <Chore detail={data} />
}

function Chore({ detail }: { detail: ChoreDetail }) {
    const { chore, runs } = detail
    const now = useNow()
    const runsOrder = useListOrder('chore-runs')
    return (
        <>
            <PageHeader title={choreRef(chore.name)}>
                Recurring work the overseer runs when it is due. What it finds reaches the attention list; your notes
                reach its next runs.
            </PageHeader>
            {/* On a wide screen the notes sit beside what the chore is and found, as a ticket's conversation does. */}
            <div
                className={cn(
                    'flex flex-col gap-6',
                    '2xl:grid 2xl:grid-cols-[minmax(0,40rem)_minmax(0,1fr)] 2xl:items-start',
                )}
            >
                <div className="stagger flex flex-col gap-6">
                    <Panel>
                        <PanelHeader label="Schedule">
                            <span className="readout text-xs text-muted-foreground">{choreLine(chore, now)}</span>
                        </PanelHeader>
                        <Fields>
                            <Field label="at most" mono>
                                every {chore.every_minutes} minutes
                            </Field>
                            <Field label="starts" mono>
                                {windowText(chore)}
                            </Field>
                            <Field label="when" className="whitespace-pre-wrap">
                                {chore.when ?? <span className="font-mono text-xs">whenever it is due</span>}
                            </Field>
                        </Fields>
                    </Panel>
                    <Panel data-testid="chore-findings">
                        <PanelHeader label="Open findings">
                            <span className="readout text-xs text-muted-foreground">{chore.findings.length}</span>
                        </PanelHeader>
                        {chore.findings.length === 0 ? (
                            <Empty>no open findings now: its latest ok run found nothing</Empty>
                        ) : (
                            <PanelScroll label="Open findings">
                                <ul className="divide-y">
                                    {chore.findings.map((finding) => (
                                        <ChoreFindingRow key={finding.id} finding={finding} chore={chore.name} />
                                    ))}
                                </ul>
                            </PanelScroll>
                        )}
                    </Panel>
                    <Panel>
                        <PanelHeader label="Recent runs">
                            <span className="flex items-center gap-2">
                                {runs.length > 1 && <OrderToggle list="chore-runs" />}
                                <span className="readout text-xs text-muted-foreground">{runs.length}</span>
                            </span>
                        </PanelHeader>
                        {runs.length === 0 ? (
                            <Empty>no runs yet: the overseer starts one when it is due</Empty>
                        ) : (
                            <PanelScroll label="Recent runs">
                                <ul className="divide-y" data-testid="chore-runs">
                                    {ordered('chore-runs', runsOrder, runs).map((run) => (
                                        <RunRow key={run.id} name={chore.name} run={run} />
                                    ))}
                                </ul>
                            </PanelScroll>
                        )}
                    </Panel>
                    <Panel data-testid="chore-spend">
                        <PanelHeader label="Spend">
                            <span className="readout text-xs text-muted-foreground">
                                {costText(chore.spend.month.cost_usd)} in 30 days
                            </span>
                        </PanelHeader>
                        <SpendTable spend={chore.spend} />
                    </Panel>
                </div>
                <Panel data-testid="chore-notes">
                    <ChoreNotes detail={detail} />
                </Panel>
            </div>
        </>
    )
}

/** A chore run: its state, id (opening its page), findings, cost, and when; what it said; its session. */
function RunRow({ name, run }: { name: string; run: ChoreRun }) {
    return (
        <ListRow kind="own-run" data-testid={`chore-run-${run.id}`}>
            <span className={cn('flex items-center gap-1.5 font-mono text-xs', RUN_TEXT[run.state])}>
                <RunDot state={run.state} />
                {run.status}
            </span>
            <span className="flex items-center gap-3">
                <Link
                    to="/chores/$name/runs/$id"
                    params={{ name, id: String(run.id) }}
                    className="readout min-w-28 text-xs text-accent underline-offset-4 hover:underline"
                >
                    {choreRunRef(name, run.id)}
                </Link>
                {run.status === 'ok' && <Chip>{run.findings === 1 ? '1 finding' : `${run.findings} findings`}</Chip>}
            </span>
            <span className="readout text-right text-xs text-muted-foreground">
                {run.cost_usd === null ? '' : `$${run.cost_usd.toFixed(2)}`}
            </span>
            <Ended started={run.started_at} ended={run.ended_at} />
            {run.summary && <RichText text={run.summary} lines={SUMMARY_LINES} className={rowLineFrom('facts')} />}
            <RowLine
                from="facts"
                className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs text-muted-foreground"
            >
                {run.session_id && (
                    <span title="open its transcript with the runtime's tools">session {run.session_id}</span>
                )}
                <span title="the run's output">log {run.log_path}</span>
            </RowLine>
        </ListRow>
    )
}

/**
 * What a chore's runs cost in each window: how many, the total, and a run's average, 99th percentile, and most. The
 * three are over the runs that reported a cost; under 100 of them, the percentile is the dearest run, as max is.
 */
function SpendTable({ spend }: { spend: ChoreSpend }) {
    const windows: [string, ChoreSpendWindow][] = [
        ['last 24 hours', spend.day],
        ['last 30 days', spend.month],
    ]
    return (
        <div className="overflow-x-auto p-3">
            <table className="border-collapse text-sm" data-testid="chore-spend-table">
                <thead>
                    <tr className="text-right">
                        <th className="panel-label w-32 pb-1.5 text-left font-normal">window</th>
                        <th className="panel-label w-24 pb-1.5 font-normal">runs</th>
                        <th className="panel-label w-24 pb-1.5 font-normal">total</th>
                        <th className="panel-label w-24 pb-1.5 font-normal">average</th>
                        <th className="panel-label w-24 pb-1.5 font-normal" title="99th percentile of a run's cost">
                            p99
                        </th>
                        <th className="panel-label w-24 pb-1.5 font-normal">max</th>
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {windows.map(([label, window]) => (
                        <tr key={label} className="text-right" data-testid={`chore-spend-${window.hours}h`}>
                            <th scope="row" className="panel-label py-0.5 text-left font-normal">
                                {label}
                            </th>
                            <td className="readout">{runsText(window)}</td>
                            <td className="readout">{costText(window.cost_usd)}</td>
                            <td className="readout">{costText(window.mean_usd)}</td>
                            <td className="readout">{costText(window.p99_usd)}</td>
                            <td className="readout">{costText(window.max_usd)}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
