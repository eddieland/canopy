import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { spendBreakdownQuery } from '@/api/queries'
import type { SpendBreakdown, SpendDay } from '@/api/types'
import { Cost } from '@/components/cost'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { TickRow } from '@/components/tick-row'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import {
    axisNames,
    chartTop,
    dayHint,
    dayLabel,
    GROUP_HINT,
    GROUP_LABEL,
    SERIES,
    seriesCost,
    shareText,
    SPEND_WINDOWS,
    spendWindow,
} from '@/lib/spend'
import type { SpendWindowDays } from '@/lib/spend'
import { cn } from '@/lib/utils'

interface SpendSearch {
    days?: SpendWindowDays | undefined
}

// Each kind of run in words, as `canopy spend` counts the runs that reported no cost.
const KIND_LABEL = {
    overseer: 'overseer runs',
    workers: 'worker and split runs',
    chores: 'chore runs',
    reviews: 'review runs',
} as const

/**
 * What agent runs cost per UTC day, by kind, and what the overseer's ticks bought, as `canopy spend` prints it. The
 * window is `?days=`, a week or 30 days; the nav opens the week, and the rail's Spent counters their own window.
 */
export const Route = createFileRoute('/spend')({
    // Typed search params: a window the page does not offer is dropped, which reads as the week.
    validateSearch: (search: Record<string, unknown>): SpendSearch => ({ days: spendWindow(search['days']) }),
    component: SpendPage,
})

function SpendPage() {
    const days = Route.useSearch().days ?? SPEND_WINDOWS[0]
    const navigate = Route.useNavigate()
    const { data } = useQuery(spendBreakdownQuery(days))
    return (
        <>
            <PageHeader title="Spend">
                What agent runs cost each UTC day, as the runtime reported it: the overseer, with idle ticks apart, and
                the workers, chores, and reviews it started. As{' '}
                <code className="font-mono text-xs">canopy spend --days {days}</code> prints it.
            </PageHeader>
            <Panel data-testid="spend-totals">
                <PanelHeader label="Totals">
                    <ToggleGroup
                        type="single"
                        value={String(days)}
                        aria-label="Window"
                        onValueChange={(value) => {
                            const picked = spendWindow(value)
                            // Pressing the window shown turns it off: keep it.
                            if (picked !== undefined) {
                                void navigate({ search: { days: picked === SPEND_WINDOWS[0] ? undefined : picked } })
                            }
                        }}
                    >
                        {SPEND_WINDOWS.map((n) => (
                            <ToggleGroupItem key={n} value={String(n)} data-testid={`spend-window-${n}`}>
                                {n} days
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                </PanelHeader>
                {data === undefined ? <PanelSkeleton className="min-h-20" /> : <Totals found={data} />}
            </Panel>
            <Panel data-testid="spend-by-day">
                <PanelHeader label="By day" />
                {data === undefined ? <PanelSkeleton rows={6} className="min-h-72" /> : <ByDay days={data.per_day} />}
            </Panel>
            <div className="grid gap-6 xl:grid-cols-2">
                <Panel data-testid="spend-ticks">
                    <PanelHeader label="Ticks by what they bought" />
                    {data === undefined ? <PanelSkeleton rows={5} className="min-h-40" /> : <TickGroups found={data} />}
                </Panel>
                <Panel data-testid="spend-woken">
                    <PanelHeader label="Ticks by what woke them" />
                    {data === undefined ? <PanelSkeleton rows={4} className="min-h-40" /> : <Woken found={data} />}
                </Panel>
            </div>
            <Panel data-testid="spend-idle-ticks">
                <PanelHeader label="Idle ticks">
                    <span className="readout text-xs text-muted-foreground">{data?.idle_ticks.length ?? ''}</span>
                </PanelHeader>
                {data === undefined ? (
                    <PanelSkeleton className="min-h-24" />
                ) : data.idle_ticks.length === 0 ? (
                    <Empty size="panel">no idle ticks in these {days} days</Empty>
                ) : (
                    <ul className="divide-y" data-testid="spend-idle-tick-list">
                        {data.idle_ticks.map((tick) => (
                            <TickRow key={tick.id} tick={tick} />
                        ))}
                    </ul>
                )}
            </Panel>
        </>
    )
}

/** The window's total, each kind's, idle ticks' share of the overseer's, and the runs that reported no cost. */
function Totals({ found }: { found: SpendBreakdown }) {
    const { totals } = found
    const cells = [
        { label: 'total', usd: totals.total, testId: 'total' },
        { label: 'overseer', usd: totals.overseer, testId: 'overseer' },
        { label: 'idle ticks', usd: totals.idle, testId: 'idle' },
        { label: 'workers and splits', usd: totals.workers, testId: 'workers' },
        { label: 'chores', usd: totals.chores, testId: 'chores' },
        { label: 'reviews', usd: totals.reviews, testId: 'reviews' },
        { label: 'dry runs', usd: totals.dry_run, testId: 'dry-run' },
    ]
    const unpriced = found.unpriced
        .filter((u) => u.unpriced > 0)
        .map((u) => `${u.unpriced} of ${u.runs} ${KIND_LABEL[u.kind]}`)
        .join(', ')
    return (
        <div className="flex flex-col gap-3 p-3">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 @md:grid-cols-4 @3xl:grid-cols-7">
                {cells.map(({ label, usd, testId }) => (
                    <div key={testId} className="flex flex-col gap-0.5">
                        <dt className="panel-label">{label}</dt>
                        <dd className="readout text-lg text-foreground" data-testid={`spend-total-${testId}`}>
                            <Cost usd={usd} />
                        </dd>
                    </div>
                ))}
            </dl>
            <p className="text-xs text-muted-foreground" data-testid="spend-idle-share">
                Idle ticks were <span className="readout text-foreground">{shareText(found.idle_share)}</span> of the
                live overseer&apos;s spend.{' '}
                {unpriced === '' ? 'Every run that ended reported a cost.' : `No cost reported: ${unpriced}.`}
            </p>
        </div>
    )
}

/**
 * Each day as a stacked bar, the series bottom up, with the legend under it, then the same numbers as a table: the
 * chart is for the eye, so a screen reader reads the table.
 */
function ByDay({ days }: { days: SpendDay[] }) {
    const top = chartTop(days)
    return (
        <div className="flex flex-col gap-4 p-3">
            <div aria-hidden className="flex flex-col gap-1.5" data-testid="spend-chart">
                <div className="flex h-48 items-end gap-1 border-b">
                    {days.map((day) => (
                        <Bar key={day.day} day={day} top={top} />
                    ))}
                </div>
                <div className="flex gap-1">
                    {days.map((day, i) => (
                        <span
                            key={day.day}
                            className="readout flex-1 truncate text-center text-2xs text-muted-foreground"
                        >
                            {axisNames(i, days.length) ? dayLabel(day.day) : ''}
                        </span>
                    ))}
                </div>
            </div>
            <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" data-testid="spend-legend">
                {SERIES.map((series) => (
                    <li key={series.key} className="flex items-center gap-1.5">
                        <span aria-hidden className={cn('size-2.5 rounded-xs', series.fill)} />
                        {series.label}
                    </li>
                ))}
            </ul>
            <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm" data-testid="spend-table">
                    <thead>
                        <tr className="text-right">
                            <th className="panel-label pb-1.5 text-left font-normal">day</th>
                            {SERIES.map((series) => (
                                <th key={series.key} className="panel-label pb-1.5 font-normal">
                                    {series.label}
                                </th>
                            ))}
                            <th className="panel-label pb-1.5 font-normal">total</th>
                        </tr>
                    </thead>
                    <tbody className="font-mono text-xs">
                        {days.toReversed().map((day) => (
                            <tr key={day.day} className="text-right" data-testid={`spend-day-${day.day}`}>
                                <th scope="row" className="readout py-0.5 text-left font-normal">
                                    {dayLabel(day.day)}
                                </th>
                                {SERIES.map((series) => (
                                    <td key={series.key} className="readout text-muted-foreground">
                                        <Cost usd={costOf(day, series.key)} />
                                    </td>
                                ))}
                                <td className="readout text-foreground">
                                    <Cost usd={day.costs.total} />
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

/** One day's bar: a segment per series it has, each as tall as its share of the chart's top. */
function Bar({ day, top }: { day: SpendDay; top: number }) {
    return (
        <div
            className="flex h-full min-w-0 flex-1 flex-col-reverse rounded-t-xs hover:bg-surface-raised"
            title={dayHint(day)}
            data-testid={`spend-bar-${day.day}`}
        >
            {top > 0 &&
                SERIES.map((series) => {
                    const usd = seriesCost(day.costs, series.key)
                    return usd > 0 ? (
                        <span
                            key={series.key}
                            className={cn('w-full shrink-0 first:rounded-none last:rounded-t-xs', series.fill)}
                            style={{ height: `${(usd / top) * 100}%` }}
                        />
                    ) : null
                })}
        </div>
    )
}

/** A series' cost on a day for the table: a dash when nothing in it reported one, as everywhere else. */
function costOf(day: SpendDay, key: (typeof SERIES)[number]['key']): number | null {
    if (key === 'overseer') {
        return day.costs.overseer === null ? null : seriesCost(day.costs, key)
    }
    return day.costs[key]
}

/** The ticks that ended in the window, a row per group, with idle ticks' share. */
function TickGroups({ found }: { found: SpendBreakdown }) {
    return (
        <CountTable
            rows={found.ticks.map((g) => ({
                key: g.group,
                label: GROUP_LABEL[g.group],
                hint: GROUP_HINT[g.group],
                ticks: g.ticks,
                usd: g.cost_usd,
            }))}
            testId="spend-groups"
        />
    )
}

/** The loop's live ticks by what ended the wait before each, the most common first. */
function Woken({ found }: { found: SpendBreakdown }) {
    if (found.woken.length === 0) {
        return <Empty size="panel">no tick canopy loop ran in these {found.days} days</Empty>
    }
    return (
        <CountTable
            rows={found.woken.map((w) => ({ key: w.by, label: w.by, ticks: w.ticks, usd: w.cost_usd }))}
            testId="spend-woken-table"
        />
    )
}

/** Rows of a label, a tick count, and what those ticks' overseers cost. */
function CountTable({
    rows,
    testId,
}: {
    rows: { key: string; label: string; hint?: string; ticks: number; usd: number | null }[]
    testId: string
}) {
    return (
        <div className="p-3">
            <table className="w-full border-collapse text-sm" data-testid={testId}>
                <thead>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">ticks</th>
                        <th className="panel-label pb-1.5 font-normal">count</th>
                        <th className="panel-label pb-1.5 font-normal">spent</th>
                    </tr>
                </thead>
                <tbody className="font-mono text-xs">
                    {rows.map((row) => (
                        <tr key={row.key} className="text-right" data-testid={`${testId}-${row.key}`}>
                            <th scope="row" className="py-0.5 text-left font-normal" title={row.hint}>
                                {row.label}
                            </th>
                            <td className="readout">{row.ticks}</td>
                            <td className="readout">
                                <Cost usd={row.usd} />
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
