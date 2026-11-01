// A report's headline figure against the same figure over the window before (ui/DESIGN.md, "Readout tiles").

import { costText } from '@/lib/cost-total'
import { hoursText } from '@/lib/reports'

/** Which way a figure is better, where the page says: a failure rate is better `down`, green first time `up`. */
export type Better = 'up' | 'down'

/** How a figure moved since the window before, as its tile says it. */
export interface ReadoutDelta {
    /** The change in its unit with its sign, `+3`, `−$1.20`, or `same` when it did not move. */
    text: string
    /** Which way it moved. */
    direction: 'up' | 'down' | 'same'
    /**
     * Whether the move is for the worse, by what the page says is better: only then does the tile color it, in the
     * failed state's color. A figure with no better way, such as spend, is never worse.
     */
    worse: boolean
}

/**
 * How `now` moved from `before`, the figure over the window before, with the change written by `format` (its size,
 * unsigned) and its sign before it; `better`, when the page says which way is better, marks a move the other way as
 * worse. Null when either figure is missing, as a window before with nothing in it to compare is.
 */
export function readoutDelta(
    now: number | null | undefined,
    before: number | null | undefined,
    format: (size: number) => string,
    better?: Better,
): ReadoutDelta | null {
    if (now === null || now === undefined || before === null || before === undefined) {
        return null
    }
    const change = now - before
    // The same figure, as its unit writes it, is the same: a cent's float noise is no move.
    if (change === 0 || format(Math.abs(change)) === format(0)) {
        return { text: 'same', direction: 'same', worse: false }
    }
    const direction = change > 0 ? 'up' : 'down'
    return {
        text: `${change > 0 ? '+' : '−'}${format(Math.abs(change))}`,
        direction,
        worse: better !== undefined && better !== direction,
    }
}

/** A count's change, whole: `3`. */
export function wholeChange(size: number): string {
    return String(Math.round(size))
}

/** A share's change, 0 to 1, in whole percentage points: `5 pts`. */
export function pointsChange(size: number): string {
    return `${Math.round(size * 100)} pts`
}

/** A cost's change, as every cost is written: `$1.20`. */
export function usdChange(size: number): string {
    return costText(size)
}

/** A span's change in hours, as the reports write a span: `45m`, `5.2h`. */
export function hoursChange(size: number): string {
    return hoursText(size)
}
