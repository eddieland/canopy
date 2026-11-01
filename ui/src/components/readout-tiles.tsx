import type { ReactNode } from 'react'

import { Hinted } from '@/components/tip'
import { Skeleton } from '@/components/ui/skeleton'
import type { ReadoutDelta } from '@/lib/readout-delta'
import { cn } from '@/lib/utils'

/** One of a report's headline figures, as its tile shows it. */
export interface ReadoutTile {
    /** What it is, its test id's end: `spend-total-workers`. */
    key: string
    /** Its name over it. */
    label: string
    /** What it counts, on its name's tip. */
    hint?: string | undefined
    /** The figure, in its unit; undefined while it is read, which holds its place. */
    value: ReactNode
    /** How it moved since the window before, when the page has that window's figure. */
    delta?: ReadoutDelta | null | undefined
}

/**
 * A report's headline figures (ui/DESIGN.md, "Readout tiles"), each a `panel-label` name over a `readout text-xl`
 * figure, a description list so a screen reader hears each name with its figure. A name with a hint shows it in a
 * `Tip`. A figure with a delta has it under it, against `against`, the window before in words (`the 7 days before`):
 * muted, unless the page says which way is better and it moved the other, in the failed state's color. Laid out in a
 * row that wraps, or in `className`'s grid.
 */
export function ReadoutTiles({
    tiles,
    against,
    testId,
    className,
}: {
    tiles: readonly ReadoutTile[]
    against?: string
    testId: string
    className?: string
}) {
    return (
        <dl className={cn('flex flex-wrap gap-x-8 gap-y-3', className)} data-testid={`${testId}-tiles`}>
            {tiles.map((tile) => (
                <div key={tile.key} className="flex flex-col gap-0.5">
                    <dt className="panel-label">
                        <Hinted hint={tile.hint}>{tile.label}</Hinted>
                    </dt>
                    <dd className="readout text-xl text-foreground" data-testid={`${testId}-${tile.key}`}>
                        {tile.value === undefined ? <Skeleton className="my-1 h-5 w-16" /> : tile.value}
                    </dd>
                    {tile.delta !== null && tile.delta !== undefined && (
                        <dd
                            className={cn(
                                'readout text-xs',
                                tile.delta.worse ? 'text-status-failed' : 'text-muted-foreground',
                            )}
                            data-testid={`${testId}-${tile.key}-delta`}
                        >
                            {deltaText(tile.delta, against)}
                        </dd>
                    )}
                </div>
            ))}
        </dl>
    )
}

// A delta in words, against the window before when the page names it: `+3 on the 7 days before`, `same as ...`.
function deltaText(delta: ReadoutDelta, against: string | undefined): string {
    if (against === undefined) {
        return delta.text
    }
    return delta.direction === 'same' ? `same as ${against}` : `${delta.text} on ${against}`
}
