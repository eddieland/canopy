// What the charts share (ui/DESIGN.md, "Charts"): the room over the peak, and how often an axis names a mark.

/** A chart's top is its peak and this much over it, the room the peak's label sits in. */
export const HEADROOM = 1.25

// The steps an axis may name its marks at, finest first.
const STEPS = [1, 2, 5, 10, 20, 50, 100] as const

/** What a measured axis has room for: the distance from one mark to the next, and the widest name with its gap. */
export interface AxisRoom {
    /** From one mark's center to the next's, in pixels. */
    pitch: number
    /** The widest name the axis can show and the space it keeps from the next, in pixels. */
    label: number
}

/**
 * How often a chart's axis names a mark, as a step back from the last: every mark of up to `all`, every fifth past
 * that, and coarser still where names that often would not fit side by side in `room`, once the chart is measured.
 * A name is never cut to fit: the axis names fewer marks instead.
 */
export function axisStep(count: number, all: number, room?: AxisRoom): number {
    const finest = count <= all ? 1 : 5
    const step = STEPS.find((s) => s >= finest && (room === undefined || s * room.pitch >= room.label))
    // Not even every hundredth fits: the last alone.
    return step ?? Math.max(count, 1)
}

/** Whether the axis names the mark at `index` of `count`, `step` apart back from the last, so the last is named. */
export function axisNames(index: number, count: number, step: number): boolean {
    return (count - 1 - index) % step === 0
}

/** Where a chart's peak is among its bars' totals, the latest of any equal, so its value sits over it; -1 for none. */
export function peakIndex(totals: readonly number[]): number {
    const top = Math.max(0, ...totals)
    return top === 0 ? -1 : totals.lastIndexOf(top)
}

/** One series of a day chart: what it counts, its name in the legend, what that means on hover, and its fill. */
export interface DayChartSeries {
    /** What it counts, its segments' key. */
    key: string
    /** Its name, as the legend and the page's table say it. */
    label: string
    /** What it counts, on its name's hover. */
    hint: string
    /** Its fill, written out so Tailwind finds it: a fill token, never a state's color. */
    fill: string
}

/** One bar of a day chart: a day, or an hour, its series' values stacked bottom up. */
export interface DayBar {
    /** The day's or the hour's name, as the server gives it, `2026-10-07`: its key and its test ids'. */
    key: string
    /** Its name on the axis: `Oct 7`, `14:00`. */
    label: string
    /** It on hover, with its values in their units. */
    hint: string
    /** Its whole, which sets its height against the chart's top. */
    total: number
    /** Its whole as said over its bar when it is the chart's peak: `$4.50`, `6`. */
    totalText: string
    /** Each series' value, bottom up; a series at 0 draws nothing. */
    segments: readonly { key: string; fill: string; value: number }[]
}
