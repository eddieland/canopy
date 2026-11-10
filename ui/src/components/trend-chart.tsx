import { useState } from 'react'
import type { PointerEvent } from 'react'

import { useClock } from '@/lib/clock'
import { clockTime } from '@/lib/time'
import { across, areaPath, linePath, nearest, upTo, VIEW_HEIGHT, VIEW_WIDTH } from '@/lib/trend'
import type { Trend, TrendPoint } from '@/lib/trend'
import { cn } from '@/lib/utils'

/** A line a trend chart draws across its plot: a value the measure is worth reading against. */
export interface TrendReference {
    /** Where it stands, in the measure's own unit. */
    value: number
    /** What it is, beside it at the plot's right edge: `12 cores`, `floor 2 GiB`. */
    label: string
}

/**
 * One measure of the machine over the last hour (ui/DESIGN.md, "Charts"): its label and its latest value over a line
 * of every reading from zero, the area under it washed in the accent, broken where the server was not reading, with
 * how long ago the chart starts and `now` under it. A pointer over the plot snaps a crosshair to the nearest reading,
 * and the value over the chart says that reading's value and time in the latest's place. The plot is for the eye: a
 * screen reader reads what it shows in words, the latest value, the peak, and the low.
 *
 * Over the plot it names the latest value and the extreme that matters, the peak, or the low for what runs out, such
 * as free space. Where the page already says the latest value beside it, `latest` false leaves it out, and the low
 * too while it is the latest.
 */
export function TrendChart({
    label,
    detail,
    trend,
    top,
    format,
    reference,
    extreme = 'peak',
    latest: showLatest = true,
}: {
    /** What it measures, as a panel's label: `Load`. */
    label: string
    /** What it is of, muted after the label: `the workspace and the journal`. */
    detail?: string
    /** Its readings. */
    trend: Trend
    /** The value at the plot's top edge, such as all the memory there is; a value over it is drawn at the top. */
    top: number
    /** A value as words, with its unit: `2.41`, `40.6 GiB`. */
    format: (value: number) => string
    /** A line it is read against, drawn while it is under `top`. */
    reference?: TrendReference
    /** Which extreme it names beside the latest value: the peak, or the low for what runs out. */
    extreme?: 'peak' | 'low'
    /** Whether it names the latest value over the plot; false where the page says it beside the chart. */
    latest?: boolean
}) {
    const clock = useClock()
    const [hovered, setHovered] = useState<TrendPoint | null>(null)
    const latest = trend.points.at(-1)
    const minutes = Math.round((trend.end - trend.start) / 60_000)
    const drawn = reference !== undefined && reference.value > 0 && reference.value < top ? reference : undefined
    const far = extreme === 'peak' ? trend.peak : trend.low
    // What it names with no pointer over it, after the latest value where it names that.
    const resting =
        latest === undefined || (!showLatest && far === latest.value)
            ? null
            : `${showLatest ? ' now · ' : ''}${extreme} ${format(far)}`
    const name =
        `${label}${detail === undefined ? '' : ` (${detail})`} over the last ${minutes} minutes: ` +
        `${format(latest?.value ?? 0)} now, peak ${format(trend.peak)}, low ${format(trend.low)}`

    function onMove(event: PointerEvent<HTMLDivElement>) {
        const box = event.currentTarget.getBoundingClientRect()
        const fraction = box.width > 0 ? (event.clientX - box.left) / box.width : 1
        setHovered(nearest(trend, Math.min(1, Math.max(0, fraction))) ?? null)
    }

    return (
        <figure className="flex min-w-0 flex-col gap-1.5 px-3 py-2.5" data-testid="trend-chart">
            <figcaption className="flex min-w-0 items-baseline justify-between gap-3">
                <span className="flex min-w-0 items-baseline gap-2">
                    <span className="shrink-0 panel-label">{label}</span>
                    {detail !== undefined && <span className="truncate text-xs text-muted-foreground">{detail}</span>}
                </span>
                {hovered === null ? (
                    <Resting latest={showLatest ? latest : undefined} format={format} resting={resting} />
                ) : (
                    <span className="shrink-0 readout text-xs" data-testid="trend-value">
                        {format(hovered.value)}
                        <span className="text-muted-foreground"> at {clockTime(iso(hovered.at), clock)}</span>
                    </span>
                )}
            </figcaption>
            {/* The plot is for the eye; a screen reader hears what it shows, in words. */}
            <p className="sr-only">{name}</p>
            <div
                aria-hidden
                className="relative h-20 touch-none"
                data-testid="trend-plot"
                onPointerMove={onMove}
                onPointerLeave={() => {
                    setHovered(null)
                }}
            >
                {/* The baseline, as the disks' bars sit on their track. */}
                <div aria-hidden className="absolute inset-x-0 bottom-0 border-t" />
                <svg
                    aria-hidden
                    className="absolute inset-0 size-full overflow-visible"
                    viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
                    preserveAspectRatio="none"
                >
                    {trend.runs.map((run) => (
                        <g key={run[0]?.at}>
                            <path d={areaPath(trend, run, top)} className="fill-accent/10" />
                            <path
                                d={linePath(trend, run, top)}
                                className="fill-none stroke-accent"
                                strokeWidth={2}
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                vectorEffect="non-scaling-stroke"
                            />
                        </g>
                    ))}
                </svg>
                {/* After the line, so its name sits over the area's fill rather than under it. */}
                {drawn !== undefined && (
                    <div
                        aria-hidden
                        className="absolute inset-x-0 border-t border-muted-foreground/40"
                        style={{ bottom: pct(upTo(drawn.value, top)) }}
                    >
                        <span className="absolute right-0 bottom-0.5 text-xs text-muted-foreground">{drawn.label}</span>
                    </div>
                )}
                {hovered !== null && (
                    <>
                        <div
                            aria-hidden
                            className="absolute inset-y-0 w-px bg-muted-foreground/60"
                            style={{ left: pct(across(trend, hovered.at)) }}
                        />
                        <div
                            aria-hidden
                            className={cn(
                                'absolute size-2 -translate-x-1/2 translate-y-1/2',
                                'rounded-full bg-accent ring-2 ring-surface',
                            )}
                            style={{ left: pct(across(trend, hovered.at)), bottom: pct(upTo(hovered.value, top)) }}
                        />
                    </>
                )}
            </div>
            <div aria-hidden className="flex justify-between text-xs text-muted-foreground">
                <span>{minutes} min ago</span>
                <span>now</span>
            </div>
        </figure>
    )
}

// What the chart names over its plot with no pointer over it: the latest value, where it names that, then `resting`.
function Resting({
    latest,
    format,
    resting,
}: {
    latest: TrendPoint | undefined
    format: (value: number) => string
    resting: string | null
}) {
    if (resting === null) {
        return null
    }
    return (
        <span
            className={cn('shrink-0 readout text-xs', latest === undefined && 'text-muted-foreground')}
            data-testid="trend-value"
        >
            {latest === undefined ? null : format(latest.value)}
            <span className="text-muted-foreground">{resting}</span>
        </span>
    )
}

// A share as a CSS percentage.
function pct(share: number): string {
    return `${share * 100}%`
}

// Milliseconds since the epoch as the ISO time the clock's helpers read.
function iso(at: number): string {
    return new Date(at).toISOString()
}
