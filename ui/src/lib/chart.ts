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
