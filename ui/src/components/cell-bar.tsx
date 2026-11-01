import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * A figure in a table's cell with a bar of its share of the column's largest after it (ui/DESIGN.md, "A bar in a
 * cell"): spent by ticket, by model, by landed ticket. `percent` is that share, 0 to 100 (`barPercent`); `fill` the
 * bar's, `muted-foreground` unless the figure is a series' with a fill of its own. The figure keeps `valueClassName`'s
 * width, so the bars of a column start at one edge. The bar is the eye's: a screen reader reads the figure.
 */
export function CellBar({
    percent,
    fill = 'bg-muted-foreground',
    valueClassName,
    children,
}: {
    percent: number
    fill?: string
    valueClassName?: string
    children: ReactNode
}) {
    return (
        <span className="flex items-center gap-2">
            <span className={cn('shrink-0', valueClassName)}>{children}</span>
            <span aria-hidden className="h-1.5 min-w-16 flex-1 rounded-full bg-surface-raised" data-testid="cell-bar">
                <span
                    className={cn('block h-full rounded-full', fill)}
                    style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
                />
            </span>
        </span>
    )
}
