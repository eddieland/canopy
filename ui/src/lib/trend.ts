// A measure of the machine over the last hour, as the system resources page's graphs draw it (ui/DESIGN.md,
// "Charts"): the server's readings of it (`hostSamplesQuery`), split where the server was not reading, and the paths
// that draw them in a box VIEW_WIDTH by VIEW_HEIGHT, which the chart stretches to its size.

import type { HostHistory, HostSample } from '@/api/types'

/** The width of the box a trend's paths are drawn in, whatever the chart's size. */
export const VIEW_WIDTH = 1000
/** The height of the box a trend's paths are drawn in. */
export const VIEW_HEIGHT = 100

// Readings further apart than this many of the server's steps have a gap between them, where it was not reading: a
// restart, or a read that failed. A little over one, so a reading late by a second does not break the line.
const GAP_STEPS = 2.5

/** One reading of a measure. */
export interface TrendPoint {
    /** When it was read, in milliseconds since the epoch. */
    at: number
    /** What it read. */
    value: number
}

/** A measure's readings over the hour its chart spans. */
export interface Trend {
    /** Every reading of it, oldest first: what the crosshair snaps to. */
    points: TrendPoint[]
    /** The readings in runs with no gap between them, oldest first: each is drawn as a line of its own. */
    runs: TrendPoint[][]
    /** Where the chart starts, in milliseconds since the epoch: as long before `end` as the server keeps readings. */
    start: number
    /** Where the chart ends: the server's latest reading, so a frozen clock and a slow one draw the same. */
    end: number
    /** The largest value read. */
    peak: number
    /** The smallest value read. */
    low: number
}

/**
 * The trend of what `pick` reads from each of `history`'s samples, or null when it read nothing, as off Linux for
 * what only `/proc` says. A sample it reads nothing from breaks the line there, as a gap in the readings does.
 */
export function trend(history: HostHistory, pick: (sample: HostSample) => number | null): Trend | null {
    const last = history.samples.at(-1)
    if (last === undefined) {
        return null
    }
    const step = history.every_seconds * 1000
    const points: TrendPoint[] = []
    const runs: TrendPoint[][] = []
    let run: TrendPoint[] = []
    for (const sample of history.samples) {
        const value = pick(sample)
        const at = Date.parse(sample.at)
        const before = run.at(-1)
        if (value === null || (before !== undefined && at - before.at > step * GAP_STEPS)) {
            run = close(runs, run)
        }
        if (value !== null) {
            const point = { at, value }
            points.push(point)
            run.push(point)
        }
    }
    close(runs, run)
    if (points.length === 0) {
        return null
    }
    const values = points.map((p) => p.value)
    const end = Date.parse(last.at)
    return {
        points,
        runs,
        start: end - Math.max(history.kept - 1, 1) * step,
        end,
        peak: Math.max(...values),
        low: Math.min(...values),
    }
}

/** Where `at` falls across the chart, from 0 at its start to 1 at its end. */
export function across(t: Trend, at: number): number {
    return t.end > t.start ? Math.min(1, Math.max(0, (at - t.start) / (t.end - t.start))) : 1
}

/** How high `value` stands on a chart whose top is `top`, from 0 at the baseline to 1 at the top. */
export function upTo(value: number, top: number): number {
    return top > 0 ? Math.min(1, Math.max(0, value / top)) : 0
}

/**
 * A run's line, as an SVG path in the view's box, `top` at its top edge. A run of one reading is a line of no length,
 * which a round cap draws as a dot.
 */
export function linePath(t: Trend, run: readonly TrendPoint[], top: number): string {
    const [first] = run
    if (first === undefined) {
        return ''
    }
    const steps = run.length === 1 ? [first, first] : run
    return steps.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(t, p.at)},${y(p.value, top)}`).join(' ')
}

/** The area under a run's line down to the baseline, as an SVG path in the view's box. */
export function areaPath(t: Trend, run: readonly TrendPoint[], top: number): string {
    const first = run[0]
    const last = run.at(-1)
    if (first === undefined || last === undefined || run.length < 2) {
        return ''
    }
    return `${linePath(t, run, top)} L${x(t, last.at)},${VIEW_HEIGHT} L${x(t, first.at)},${VIEW_HEIGHT} Z`
}

/** The reading nearest `fraction` of the way across the chart, for the crosshair to snap to. */
export function nearest(t: Trend, fraction: number): TrendPoint | undefined {
    const at = t.start + fraction * (t.end - t.start)
    let found: TrendPoint | undefined
    for (const point of t.points) {
        if (found === undefined || Math.abs(point.at - at) < Math.abs(found.at - at)) {
            found = point
        }
    }
    return found
}

// The run collected so far kept, if it holds a reading, and a new one to collect into.
function close(runs: TrendPoint[][], run: TrendPoint[]): TrendPoint[] {
    if (run.length > 0) {
        runs.push(run)
    }
    return []
}

// A reading's place in the view's box, to a tenth of its unit.
function x(t: Trend, at: number): number {
    return round(across(t, at) * VIEW_WIDTH)
}

function y(value: number, top: number): number {
    return round((1 - upTo(value, top)) * VIEW_HEIGHT)
}

function round(n: number): number {
    return Math.round(n * 10) / 10
}
