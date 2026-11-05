import type { SpendFirstCallWeek } from '@/api/types'
import { ReportTable } from '@/components/report-table'
import type { ReportColumn } from '@/components/report-table'
import { Tipped } from '@/components/tip'
import { HEADROOM } from '@/lib/chart'
import { snapshotsOf, weekChanges, weekHint, weekLabel } from '@/lib/first-calls'
import { shareText } from '@/lib/spend'
import { tokenCount } from '@/lib/transcript'
import { cn } from '@/lib/utils'

// What the table's columns count, on hover.
const FIRST_CALL_HINT = "The median of what the week's first calls were sent, in tokens, from the cache or not"
const FROM_CACHE_HINT = "What the week's first calls read from the cache, over what they were sent"

/**
 * One series' first model calls by week (ui/DESIGN.md, Charts): a bar per week, as tall as the share of what its first
 * calls were sent that the cache served, from zero to the whole, its rate over it, and a rule before each week whose
 * runs used a runtime version or a definitions snapshot no earlier week's did. Under it, each of those weeks names
 * what it used, several snapshots as a count with each in its tip, and a table holds the numbers, the median first
 * call among them: the chart is for the eye, so a screen reader reads the list and the table. `fill` is the kind's
 * spend series fill.
 */
export function FirstCallChart({ weeks, fill }: { weeks: SpendFirstCallWeek[]; fill: string }) {
    const changed = weeks.filter((week) => weekChanges(week).length > 0)
    return (
        <div className="flex flex-col gap-4 p-3">
            <div aria-hidden className="flex flex-col gap-1.5 px-3" data-testid="first-call-chart">
                <div className="flex h-40 items-end justify-center gap-1">
                    {weeks.map((week) => (
                        <WeekBar key={week.week} week={week} fill={fill} />
                    ))}
                </div>
                <div className="flex justify-center gap-1">
                    {weeks.map((week) => (
                        <span key={week.week} className="relative h-4 max-w-24 min-w-0 flex-1">
                            <span
                                className={cn(
                                    'readout absolute left-1/2 -translate-x-1/2',
                                    'text-2xs whitespace-nowrap text-muted-foreground',
                                )}
                            >
                                {weekLabel(week.week)}
                            </span>
                        </span>
                    ))}
                </div>
            </div>
            {changed.length > 0 && (
                <ul className="flex flex-col gap-1 text-xs text-muted-foreground" aria-label="What changed">
                    {changed.map((week) => (
                        <li key={week.week} className="flex items-baseline gap-2" data-testid="first-call-change">
                            <span aria-hidden className="h-3 w-px shrink-0 self-center bg-muted-foreground" />
                            <span>
                                Week of {weekLabel(week.week)}:{' '}
                                <span className="readout break-all text-foreground">
                                    <Tipped fact={snapshotsOf(week)} mono>
                                        {weekChanges(week).join(', ')}
                                    </Tipped>
                                </span>
                            </span>
                        </li>
                    ))}
                </ul>
            )}
            {/* A block of its own, so the column's flex never stretches the table past its content. */}
            <div>
                <ReportTable
                    rows={weeks.toReversed()}
                    columns={WEEK_COLUMNS}
                    rowKey={(week) => week.week}
                    label="First calls by week"
                    scroll={false}
                    testId="first-call-table"
                    rowTestId={(week) => `first-call-week-${week.week}`}
                />
            </div>
        </div>
    )
}

// The table's columns: the week, its runs, its median first call, and the share the cache served.
const WEEK_COLUMNS: ReportColumn<SpendFirstCallWeek>[] = [
    {
        key: 'week',
        kind: 'name',
        label: 'week of',
        cell: (week) => (
            <span className="readout">
                <Tipped fact={week.week} mono>
                    {weekLabel(week.week)}
                </Tipped>
            </span>
        ),
    },
    { key: 'runs', kind: 'figure', label: 'runs', cell: (week) => week.runs },
    {
        key: 'first-call',
        kind: 'figure',
        label: 'first call',
        hint: FIRST_CALL_HINT,
        cell: (week) => tokenCount(week.first_call),
    },
    {
        key: 'from-cache',
        kind: 'figure',
        label: 'from cache',
        hint: FROM_CACHE_HINT,
        cell: (week) => shareText(week.hit_rate),
        tone: (week) => week.hit_rate === null && 'text-muted-foreground',
    },
]

/**
 * One week's bar: its hit rate's share of the plot, whose top is the whole and `HEADROOM` over it, so the rate written
 * over a full bar stays inside. A week whose runs recorded no cache read is a stub on the baseline. A week that used a
 * new runtime version or snapshot has a rule down its left edge, in the gap from the week before.
 */
function WeekBar({ week, fill }: { week: SpendFirstCallWeek; fill: string }) {
    const height = ((week.hit_rate ?? 0) / HEADROOM) * 100
    const marked = weekChanges(week).length > 0
    return (
        <div
            className={cn(
                'relative flex h-full max-w-24 min-w-0 flex-1 flex-col justify-end',
                'rounded-t-xs hover:bg-surface-raised',
            )}
            title={weekHint(week)}
            data-testid={`first-call-bar-${week.week}`}
        >
            {marked && (
                <span
                    className="absolute inset-y-0 -left-0.5 w-px bg-muted-foreground"
                    data-testid="first-call-marker"
                />
            )}
            {week.hit_rate === null ? (
                <span className="h-px w-full shrink-0 bg-border" />
            ) : (
                <span className={cn('min-h-0.5 w-full shrink-0 rounded-t-xs', fill)} style={{ height: `${height}%` }} />
            )}
            <span
                className="readout absolute inset-x-0 flex justify-center pb-0.5 text-2xs whitespace-nowrap"
                style={{ bottom: `${height}%` }}
            >
                {shareText(week.hit_rate)}
            </span>
        </div>
    )
}
