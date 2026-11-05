import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { choreQuery } from '@/api/queries'
import type { ChoreDetail, ChoreRun, ChoreSpend, ChoreSpendWindow } from '@/api/types'
import { Age } from '@/components/age'
import { ChoreFindingRow } from '@/components/chore-finding'
import { ChoreLimitBanner } from '@/components/chore-limit'
import { ChoreRunLink } from '@/components/chore-link'
import { ChoreNotes } from '@/components/chore-notes'
import { Copyable, CopyablePath } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { Field, Fields } from '@/components/fields'
import { Notice } from '@/components/notice'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll } from '@/components/panel'
import { ReportTable } from '@/components/report-table'
import type { ReportColumn } from '@/components/report-table'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { ListRow, RowLine, RowList } from '@/components/rows'
import { RunDot, Word } from '@/components/status'
import { TryChore } from '@/components/try-chore'
import {
    cadenceText,
    choreHealth,
    findingsReadout,
    listedText,
    runsText,
    startsAnyTime,
    windowText,
} from '@/lib/chores'
import { costText } from '@/lib/cost-total'
import { ordered, useListOrder } from '@/lib/list-order'
import { choreRef } from '@/lib/refs'
import { rowLineFrom } from '@/lib/rows'
import { RUN_TEXT } from '@/lib/run-state'
import { useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

// A window of a chore's spend, by its name.
type SpendWindow = [string, ChoreSpendWindow]

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
                {choreHealth(chore, now)}
            </PageHeader>
            <ChoreLimitBanner chore={chore} />
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
                <Panel className="2xl:col-start-1 2xl:row-start-1" data-testid="chore-schedule">
                    {/* Where it stands, how its last run ended, and its open findings are the page's description. A
                        window or condition left at its default is no row: only what the config says is a fact. */}
                    <PanelHeader label="Schedule" />
                    <Fields>
                        <Field label="at most" mono>
                            {cadenceText(chore.every_minutes)}
                        </Field>
                        {!startsAnyTime(chore) && (
                            <Field label="starts" mono>
                                {windowText(chore)}
                            </Field>
                        )}
                        {chore.when !== null && (
                            <Field label="when" className="whitespace-pre-wrap">
                                {chore.when}
                            </Field>
                        )}
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
                                {findingsReadout(chore.findings, chore.more_findings)}
                            </span>
                        </PanelHeader>
                        {chore.findings.length === 0 ? (
                            <Empty>
                                {chore.more_findings > 0
                                    ? 'no open findings listed: its latest ok run counted some past its max_findings'
                                    : 'no open findings now: its latest ok run found nothing'}
                            </Empty>
                        ) : (
                            <PanelScroll label="Open findings">
                                <RowList kind="finding" className="divide-y">
                                    {chore.findings.map((finding) => (
                                        <ChoreFindingRow key={finding.id} finding={finding} chore={chore.name} />
                                    ))}
                                </RowList>
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
                                <RowList kind="own-run" className="divide-y" data-testid="chore-runs">
                                    {ordered('chore-runs', runsOrder, runs).map((run) => (
                                        <RunRow key={run.id} name={chore.name} run={run} />
                                    ))}
                                </RowList>
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
                        {listedText(run.findings, run.more_findings)}
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
    const windows: SpendWindow[] = [
        ['last 24 hours', spend.day],
        ['last 30 days', spend.month],
    ]
    return (
        <ReportTable
            rows={windows}
            columns={SPEND_COLUMNS}
            rowKey={([label]) => label}
            label="Spend"
            className="px-3 pb-3"
            testId="chore-spend-table"
            rowTestId={([, window]) => `chore-spend-${window.hours}h`}
        />
    )
}

/** The spend table's columns: the window, its runs, their total, and a run's average, 99th percentile, and most. */
const SPEND_COLUMNS: ReportColumn<SpendWindow>[] = [
    { key: 'window', kind: 'name', label: 'window', cell: ([label]) => label },
    { key: 'runs', kind: 'figure', label: 'runs', cell: ([, window]) => runsText(window) },
    { key: 'total', kind: 'figure', label: 'total', cell: ([, window]) => costText(window.cost_usd) },
    { key: 'average', kind: 'figure', label: 'average', cell: ([, window]) => costText(window.mean_usd) },
    {
        key: 'p99',
        kind: 'figure',
        label: 'p99',
        hint: "99th percentile of a run's cost",
        cell: ([, window]) => costText(window.p99_usd),
    },
    { key: 'max', kind: 'figure', label: 'max', cell: ([, window]) => costText(window.max_usd) },
]
