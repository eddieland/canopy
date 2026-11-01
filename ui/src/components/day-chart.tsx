import { Hinted } from '@/components/tip'
import { useMeasure } from '@/hooks/use-measure'
import { axisNames, axisStep, HEADROOM, peakIndex } from '@/lib/chart'
import type { AxisRoom, DayBar, DayChartSeries } from '@/lib/chart'
import { cn } from '@/lib/utils'

// The axis names every day of up to a week, and every fifth day or hour past that, back from the latest.
const AXIS_ALL = 7
// The widest name the axis leaves room for at least, `Sep 30`, in characters, and the space it keeps from the next, in
// pixels. An hour on a 12-hour clock, `12:00 PM`, is wider, and gets its own.
const AXIS_NAME_CHARS = 6
const AXIS_GAP = 8

// Where the peak's total sits over its bar (`peakAlign`), and the class that puts it there.
type PeakAlign = 'start' | 'center' | 'end'
const PEAK_JUSTIFY: Record<PeakAlign, string> = {
    start: 'justify-start',
    center: 'justify-center',
    end: 'justify-end',
}

/**
 * A day's or an hour's bars over their axis (ui/DESIGN.md, Charts), the row centered and each bar 3rem at most, so a
 * sparse window draws narrow bars rather than slabs. The axis names a day centered under its bar, whole, wider than the
 * bar where it must be; where names that often would touch, it names fewer days (`axisStep`). The peak's total sits
 * over its bar. It is for the eye, so it is hidden from a screen reader: the page puts a table of the same numbers
 * under it. `testId` prefixes each part's test id, `spend` giving `spend-chart`, `spend-bar-2026-10-07`, and so on.
 * Give it a `key` of its bars' count, so another window, another pitch, is measured afresh. A chart whose bars pick
 * something below it, as the reports page's months do, marks the one `marked` in the accent's tint and calls `onPick`
 * with a bar's key on its click; the page keeps a link for each in the table, for the keyboard.
 */
export function DayChart({
    bars,
    testId,
    marked,
    onPick,
}: {
    bars: readonly DayBar[]
    testId: string
    marked?: string | undefined
    onPick?: ((key: string) => void) | undefined
}) {
    const widest = Math.max(AXIS_NAME_CHARS, ...bars.map((bar) => bar.label.length))
    // The same room is the same state: a new object each time would render again for nothing.
    const [measure, room] = useMeasure((chart: HTMLElement) => axisRoom(chart, widest), undefined, { same: sameRoom })
    const top = Math.max(0, ...bars.map((bar) => bar.total)) * HEADROOM
    const peak = peakIndex(bars.map((bar) => bar.total))
    const step = axisStep(bars.length, AXIS_ALL, room)
    return (
        <div ref={measure} aria-hidden className="flex flex-col gap-1.5 px-3" data-testid={`${testId}-chart`}>
            <div className="flex h-48 items-end justify-center gap-1">
                {bars.map((bar, i) => (
                    <Bar
                        key={bar.key}
                        bar={bar}
                        top={top}
                        peak={i === peak ? peakAlign(i, bars.length) : undefined}
                        marked={bar.key === marked}
                        onPick={onPick}
                        testId={testId}
                    />
                ))}
            </div>
            <div className="flex justify-center gap-1">
                {bars.map((bar, i) => (
                    <span key={bar.key} className="relative h-4 max-w-12 min-w-0 flex-1">
                        {axisNames(i, bars.length, step) && (
                            <span
                                className={cn(
                                    'readout absolute left-1/2 -translate-x-1/2',
                                    'text-2xs whitespace-nowrap text-muted-foreground',
                                )}
                                data-testid={`${testId}-axis-${bar.key}`}
                            >
                                {bar.label}
                            </span>
                        )}
                    </span>
                ))}
            </div>
        </div>
    )
}

/**
 * A day chart's legend: each series' name, `muted-foreground`, beside a swatch of its fill, what it counts in the
 * name's tip (`Hinted`), so the keyboard and a touch screen reach it. The table under the chart names its columns
 * plainly, since the legend says what each counts.
 */
export function DayChartLegend({ series, testId }: { series: readonly DayChartSeries[]; testId: string }) {
    return (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" data-testid={`${testId}-legend`}>
            {series.map((s) => (
                <li key={s.key} className="flex items-center gap-1.5">
                    <span aria-hidden className={cn('size-2.5 rounded-xs', s.fill)} />
                    <Hinted hint={s.hint}>{s.label}</Hinted>
                </li>
            ))}
        </ul>
    )
}

/**
 * What the drawn chart has room for: from one bar to the next, and the widest name a day can have, `widest`
 * characters, from the width of a name shown (the axis is monospace), with its gap. Undefined while there is nothing
 * to measure.
 */
function axisRoom(chart: HTMLElement, widest: number): AxisRoom | undefined {
    const [plot, axis] = chart.children
    const first = plot?.children[0]?.getBoundingClientRect()
    const second = plot?.children[1]?.getBoundingClientRect()
    const name = [...(axis?.children ?? [])].find((slot) => slot.firstElementChild !== null)?.firstElementChild
    const chars = name?.textContent.length ?? 0
    if (first === undefined || name === undefined || name === null || chars === 0) {
        return undefined
    }
    const width = name.getBoundingClientRect().width
    return {
        pitch: second === undefined ? Number.POSITIVE_INFINITY : Math.round(second.left - first.left),
        label: Math.ceil((width / chars) * widest) + AXIS_GAP,
    }
}

// Whether two measures of the axis leave it the same room.
function sameRoom(before: AxisRoom | undefined, after: AxisRoom | undefined): boolean {
    return before?.pitch === after?.pitch && before?.label === after?.label
}

/**
 * Where the peak's total sits over its bar: centered, but flush with the bar's outer edge on the first and the last,
 * since a total is wider than a narrow bar and the chart's padding is less than the half that would overhang.
 */
function peakAlign(i: number, count: number): PeakAlign {
    if (count > 1 && i === 0) {
        return 'start'
    }
    return count > 1 && i === count - 1 ? 'end' : 'center'
}

/**
 * One bar. Its segments stack bottom up, each its series' share of the bar, at least 2px and 2px apart, the whole as
 * tall as its total's share of the chart's top; the peak's total sits over its bar. A bar of nothing is a stub on the
 * baseline, so it reads as nothing rather than a column gone missing.
 */
function Bar({
    bar,
    top,
    peak,
    marked,
    onPick,
    testId,
}: {
    bar: DayBar
    top: number
    peak: PeakAlign | undefined
    marked: boolean
    onPick: ((key: string) => void) | undefined
    testId: string
}) {
    const segments = bar.segments.filter(({ value }) => value > 0)
    const sum = segments.reduce((total, { value }) => total + value, 0)
    const height = top === 0 ? 0 : (bar.total / top) * 100
    return (
        // The chart is the eye's, hidden from a screen reader: a click picks what the page's table links for the
        // keyboard, so the bar needs no key of its own.
        // oxlint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
        <div
            className={cn(
                'relative flex h-full max-w-12 min-w-0 flex-1 flex-col justify-end',
                'rounded-t-xs hover:bg-surface-raised',
                marked && 'bg-accent/16 hover:bg-accent/16',
                onPick !== undefined && 'cursor-pointer',
            )}
            title={bar.hint}
            data-marked={marked || undefined}
            onClick={onPick === undefined ? undefined : () => onPick(bar.key)}
            data-testid={`${testId}-bar-${bar.key}`}
        >
            {sum === 0 ? (
                <span className="h-px w-full shrink-0 bg-border" data-testid={`${testId}-stub`} />
            ) : (
                <span
                    className="flex min-h-min w-full shrink-0 flex-col-reverse gap-0.5"
                    style={{ height: `${height}%` }}
                >
                    {segments.map(({ key, fill, value }) => (
                        <span
                            key={key}
                            className={cn('min-h-0.5 w-full last:rounded-t-xs', fill)}
                            // A share of 100, not of 1: flex factors that sum under 1 leave part of the bar unfilled.
                            style={{ flexGrow: (value / sum) * 100, flexBasis: 0 }}
                            data-testid={`${testId}-segment-${key}`}
                        />
                    ))}
                </span>
            )}
            {peak !== undefined && (
                <span
                    className={cn(
                        'readout absolute inset-x-0 flex pb-0.5 text-2xs whitespace-nowrap',
                        PEAK_JUSTIFY[peak],
                    )}
                    style={{ bottom: `${height}%` }}
                    data-testid={`${testId}-peak`}
                >
                    <span>{bar.totalText}</span>
                </span>
            )}
        </div>
    )
}
