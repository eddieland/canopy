import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { choreQuery } from '@/api/queries'
import type { ChoreDetail, ChoreRun, ChoreSpend, ChoreSpendWindow } from '@/api/types'
import { Age } from '@/components/age'
import { ChoreFindingRow } from '@/components/chore-finding'
import { ChoreRunLink } from '@/components/chore-link'
import { ChoreNotes } from '@/components/chore-notes'
import { Copyable, CopyablePath } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { Field, Fields } from '@/components/fields'
import { Notice } from '@/components/notice'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll } from '@/components/panel'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { ListRow, RowLine } from '@/components/rows'
import { RunDot, Word } from '@/components/status'
import { TryChore } from '@/components/try-chore'
import { cadenceText, choreLine, findingsReadout, runsText, windowText } from '@/lib/chores'
import { costText } from '@/lib/cost-total'
import { ordered, useListOrder } from '@/lib/list-order'
import { choreRef } from '@/lib/refs'
import { rowLineFrom } from '@/lib/rows'
import { RUN_TEXT } from '@/lib/run-state'
import { useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

// What every chore's page shows, on its title's hover: its description is where the chore stands.
const HELP =
    'Recurring work the overseer runs when it is due. What it finds reaches the attention list; your notes reach its ' +
    'next runs.'

/** One chore: its schedule, its open findings, its runs, and the operator's notes to it. */
export const Route = createFileRoute('/chores/$name')({
    component: ChorePage,
})

function ChorePage() {
    const { name } = Route.useParams()
    const query = useQuery(choreQuery(name))
    const { data, error } = query
    if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        return (
            <>
                <PageHeader title={choreRef(name)} />
                <Panel>
                    {/* A chore this workspace does not define is missing, and says why; a refusal is a Notice. */}
                    {error.status === 404 ? (
                        <Empty size="panel">{error.message}</Empty>
                    ) : (
                        <Notice error={error} className="p-3" />
                    )}
                </Panel>
            </>
        )
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader title={choreRef(name)} />
                <Panel>
                    <PanelLoading query={query} rows={1} className="min-h-72" />
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
            <PageHeader title={choreRef(chore.name)} help={HELP}>
                {choreLine(chore, now)}
            </PageHeader>
            {/* The detail skeleton (DESIGN.md): what it is, then its main content, its open findings and the runs that
                found them, then its notes and spend. Wide, findings and runs take the wide column beside the rest; the
                source keeps the reading order. */}
            <div
                className={cn(
                    'stagger flex flex-col gap-6',
                    '2xl:grid 2xl:grid-cols-[minmax(0,40rem)_minmax(0,1fr)] 2xl:grid-rows-[auto_auto_1fr]',
                    '2xl:items-start',
                )}
            >
                <Panel className="2xl:col-start-1 2xl:row-start-1">
                    {/* Where it stands, running or when it last ran and is next due, is the page's description. */}
                    <PanelHeader label="Schedule" />
                    <Fields>
                        <Field label="at most" mono>
                            {cadenceText(chore.every_minutes)}
                        </Field>
                        <Field label="starts" mono>
                            {windowText(chore)}
                        </Field>
                        <Field label="when" className="whitespace-pre-wrap">
                            {chore.when ?? <span className="font-mono text-xs">whenever it is due</span>}
                        </Field>
                    </Fields>
                    <div className="border-t" data-testid="chore-actions">
                        <TryChore chore={chore} />
                    </div>
                </Panel>
                {/* One column of its own, so a long list of findings never stretches the schedule's row. */}
                <div className="flex flex-col gap-6 2xl:col-start-2 2xl:row-span-3 2xl:row-start-1">
                    <Panel data-testid="chore-findings">
                        <PanelHeader label="Open findings">
                            <span className="readout text-xs text-muted-foreground" data-testid="chore-findings-count">
                                {findingsReadout(chore.findings)}
                            </span>
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
                        <PanelHeader label="Runs">
                            <span className="flex items-center gap-2">
                                {runs.length > 1 && <OrderToggle list="chore-runs" />}
                                <span className="readout text-xs text-muted-foreground">{runs.length}</span>
                            </span>
                        </PanelHeader>
                        {runs.length === 0 ? (
                            <Empty>no runs yet: the overseer starts one when it is due</Empty>
                        ) : (
                            <PanelScroll label="Runs">
                                <ul className="divide-y" data-testid="chore-runs">
                                    {ordered('chore-runs', runsOrder, runs).map((run) => (
                                        <RunRow key={run.id} name={chore.name} run={run} />
                                    ))}
                                </ul>
                            </PanelScroll>
                        )}
                    </Panel>
                </div>
                <Panel className="2xl:col-start-1 2xl:row-start-2" data-testid="chore-notes">
                    <ChoreNotes detail={detail} />
                </Panel>
                <Panel className="2xl:col-start-1 2xl:row-start-3" data-testid="chore-spend">
                    <PanelHeader label="Spend" />
                    <SpendTable spend={chore.spend} />
                </Panel>
            </div>
        </>
    )
}

/** A chore run: its state, id (opening its page), findings, cost, and when; what it said; its session. */
function RunRow({ name, run }: { name: string; run: ChoreRun }) {
    return (
        <ListRow kind="own-run" className="group/copy" data-testid={`chore-run-${run.id}`}>
            <span className={cn('flex items-center gap-1.5 font-mono text-xs', RUN_TEXT[run.state])}>
                <RunDot state={run.state} />
                <Word word={run.status} />
            </span>
            <span className="flex items-center gap-3">
                <ChoreRunLink name={name} id={run.id} className="min-w-28" />
                {run.status === 'ok' && (
                    <span className="readout text-xs text-muted-foreground">
                        {run.findings === 1 ? '1 finding' : `${run.findings} findings`}
                    </span>
                )}
            </span>
            <Cost usd={run.cost_usd} className="text-right text-xs text-muted-foreground" />
            <Age variant="span" started={run.started_at} ended={run.ended_at} className="text-right" />
            {run.summary && <RichText text={run.summary} lines={SUMMARY_LINES} className={rowLineFrom('facts')} />}
            <RowLine
                from="facts"
                className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs text-muted-foreground"
            >
                {run.session_id && (
                    <Copyable text={run.session_id} label="session id" reveal>
                        <span title="open its transcript with the runtime's tools">session {run.session_id}</span>
                    </Copyable>
                )}
                <CopyablePath path={run.log_path} label="log path" reveal>
                    <span title="the run's output">log {run.log_path}</span>
                </CopyablePath>
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
            <table className="w-full border-collapse text-sm" data-testid="chore-spend-table">
                <thead>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">window</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">runs</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">total</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">average</th>
                        <th className="panel-label pb-1.5 pl-3 font-normal" title="99th percentile of a run's cost">
                            p99
                        </th>
                        <th className="panel-label pb-1.5 pl-3 font-normal">max</th>
                    </tr>
                </thead>
                <tbody className="text-xs">
                    {windows.map(([label, window]) => (
                        <tr key={label} className="text-right" data-testid={`chore-spend-${window.hours}h`}>
                            <th scope="row" className="w-full py-0.5 text-left font-normal">
                                {label}
                            </th>
                            <td className="readout pl-3 whitespace-nowrap">{runsText(window)}</td>
                            <td className="readout pl-3">{costText(window.cost_usd)}</td>
                            <td className="readout pl-3">{costText(window.mean_usd)}</td>
                            <td className="readout pl-3">{costText(window.p99_usd)}</td>
                            <td className="readout pl-3">{costText(window.max_usd)}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
