import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { ExternalLink } from 'lucide-react'

import { ApiError } from '@/api/client'
import { choreQuery } from '@/api/queries'
import type { ChoreDetail, ChoreFinding, ChoreRun } from '@/api/types'
import { Age } from '@/components/age'
import { ChoreNotes } from '@/components/chore-notes'
import { LinkedText } from '@/components/linked-text'
import { OrderToggle } from '@/components/order-toggle'
import { PageHeader, Panel, PanelHeader, PanelScroll, Placeholder } from '@/components/panel'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { Chip, RunDot } from '@/components/status'
import { Skeleton } from '@/components/ui/skeleton'
import { choreLine, windowText } from '@/lib/chores'
import { ordered, useListOrder } from '@/lib/list-order'
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
                <PageHeader label="Chore" title={`chore:${name}`} />
                <Panel>
                    <Placeholder className="min-h-40">{error.message}</Placeholder>
                </Panel>
            </>
        )
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader label="Chore" title={`chore:${name}`} />
                <Panel className="min-h-72 p-3">
                    <Skeleton className="h-4 w-1/2" />
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
            <PageHeader label="Chore" title={`chore:${chore.name}`}>
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
                        <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 p-3 text-sm">
                            <dt className="panel-label self-center">at most</dt>
                            <dd className="font-mono text-xs">every {chore.every_minutes} minutes</dd>
                            <dt className="panel-label self-center">starts</dt>
                            <dd className="font-mono text-xs">{windowText(chore)}</dd>
                            <dt className="panel-label">when</dt>
                            <dd className="text-sm break-words whitespace-pre-wrap">
                                {chore.when ?? <span className="font-mono text-xs">whenever it is due</span>}
                            </dd>
                        </dl>
                    </Panel>
                    <Panel data-testid="chore-findings">
                        <PanelHeader label="Open findings">
                            <span className="readout text-xs text-muted-foreground">{chore.findings.length}</span>
                        </PanelHeader>
                        {chore.findings.length === 0 ? (
                            <Placeholder className="min-h-20">none: its latest ok run found nothing</Placeholder>
                        ) : (
                            <PanelScroll label="Open findings">
                                <ul className="divide-y">
                                    {chore.findings.map((finding) => (
                                        <Finding key={finding.id} finding={finding} />
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
                            <Placeholder className="min-h-20">never run</Placeholder>
                        ) : (
                            <PanelScroll label="Recent runs">
                                <ul className="divide-y" data-testid="chore-runs">
                                    {ordered('chore-runs', runsOrder, runs).map((run) => (
                                        <RunRow key={run.id} run={run} />
                                    ))}
                                </ul>
                            </PanelScroll>
                        )}
                    </Panel>
                </div>
                <Panel data-testid="chore-notes">
                    <ChoreNotes detail={detail} />
                </Panel>
            </div>
        </>
    )
}

/** A finding: its id, its title and link, and below them its detail. All of it is the agent's: text, never markup. */
function Finding({ finding }: { finding: ChoreFinding }) {
    return (
        <li className="flex flex-col gap-1 px-3 py-2.5" data-testid={`finding-${finding.id}`}>
            <div className="flex items-center gap-3">
                <Chip>{finding.id}</Chip>
                <span className="min-w-0 truncate text-sm">{finding.title}</span>
                <Age at={finding.since} className="ml-auto" />
            </div>
            {finding.detail && (
                <p className="text-sm break-words whitespace-pre-wrap text-muted-foreground">
                    <LinkedText text={finding.detail} />
                </p>
            )}
            {finding.link && (
                <a
                    href={finding.link}
                    target="_blank"
                    rel="noreferrer noopener"
                    className={cn(
                        'inline-flex items-center gap-1 self-start font-mono text-xs text-accent underline-offset-4',
                        'hover:underline',
                    )}
                >
                    {finding.link.replace(/^https:\/\//, '')}
                    <ExternalLink className="size-3" />
                </a>
            )}
        </li>
    )
}

/** A chore run: its state, id, findings, cost, and when; what it said; its session. */
function RunRow({ run }: { run: ChoreRun }) {
    return (
        <li className="flex flex-col gap-1 px-3 py-2.5" data-testid={`chore-run-${run.id}`}>
            <div className="flex items-center gap-3">
                <span className={cn('flex w-20 items-center gap-1.5 font-mono text-xs', RUN_TEXT[run.state])}>
                    <RunDot state={run.state} />
                    {run.status}
                </span>
                <span className="readout w-14 text-xs text-muted-foreground">#{run.id}</span>
                {run.status === 'ok' && <Chip>{run.findings === 1 ? '1 finding' : `${run.findings} findings`}</Chip>}
                <span className="ml-auto flex items-center gap-4">
                    <span className="readout w-16 text-right text-xs text-muted-foreground">
                        {run.cost_usd === null ? '' : `$${run.cost_usd.toFixed(2)}`}
                    </span>
                    <span className="flex w-24 justify-end gap-1 text-xs text-muted-foreground">
                        {run.ended_at === null ? 'for' : 'ended'}
                        <Age at={run.ended_at ?? run.started_at} />
                        {run.ended_at === null ? '' : 'ago'}
                    </span>
                </span>
            </div>
            {run.summary && <RichText text={run.summary} lines={SUMMARY_LINES} className="pl-[9.5rem]" />}
            <div
                className={cn(
                    'flex flex-wrap items-center gap-x-4 gap-y-1 pl-[9.5rem]',
                    'font-mono text-xs text-muted-foreground',
                )}
            >
                {run.session_id && (
                    <span title="open its transcript with the runtime's tools">session {run.session_id}</span>
                )}
                <span title="the run's output">log {run.log_path}</span>
            </div>
        </li>
    )
}
