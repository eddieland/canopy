import { HEADROOM } from '@/lib/chart'
import { cn } from '@/lib/utils'

/** One point of a sparkline: its key, its value, null where it has none, and, with dots, what it says on hover. */
export interface SparkPoint {
    /** What tells it from the others: a day's or a month's name, its dot's test id's end. */
    key: string
    /** Its value; null where there is none, which breaks the line rather than draw a zero. */
    value: number | null
    /** What its dot says on hover. */
    hint?: string
}

/**
 * A small line of a series across its points (ui/DESIGN.md, "A sparkline"), oldest on the left, in `accent`: a trend
 * read at a glance where a table or a chart would be too much, on a report card or over a column of medians. Its
 * scale runs from 0 to its largest value and `HEADROOM` over it, as a chart's; a point with no value breaks the line.
 * With `dots`, each point with a value is a dot that says its `hint` on hover. It is for the eye, so it is hidden from
 * a screen reader: what it draws is in words or a table beside it. Its height is `className`'s, `h-8` by default.
 */
export function Sparkline({
    points,
    dots = false,
    testId,
    className,
}: {
    points: readonly SparkPoint[]
    dots?: boolean
    testId: string
    className?: string
}) {
    const top = Math.max(0, ...points.map((p) => p.value ?? 0)) * HEADROOM
    const at = (i: number, value: number) => ({
        x: points.length === 1 ? 50 : (i / (points.length - 1)) * 100,
        y: top === 0 ? 100 : 100 - (value / top) * 100,
    })
    // Each run of points with a value, drawn as its own line.
    const runs: { x: number; y: number }[][] = [[]]
    for (const [i, point] of points.entries()) {
        if (point.value === null) {
            runs.push([])
        } else {
            runs.at(-1)?.push(at(i, point.value))
        }
    }
    return (
        <div aria-hidden className={cn('relative h-8 w-full', className)} data-testid={testId}>
            <svg
                className="absolute inset-0 size-full overflow-visible"
                viewBox="0 0 100 100"
                preserveAspectRatio="none"
            >
                {runs
                    .filter((run) => run.length > 1)
                    .map((run) => (
                        <polyline
                            key={`${run[0]?.x}`}
                            points={run.map(({ x, y }) => `${x},${y}`).join(' ')}
                            className="fill-none stroke-accent"
                            strokeWidth={1.5}
                            strokeLinejoin="round"
                            vectorEffect="non-scaling-stroke"
                        />
                    ))}
            </svg>
            {points.map((point, i) => {
                if (point.value === null) {
                    return null
                }
                const { x, y } = at(i, point.value)
                // A lone point, between two with none, draws no line: it is a dot whether or not the rest are.
                const alone = (points[i - 1]?.value ?? null) === null && (points[i + 1]?.value ?? null) === null
                if (!dots && !alone) {
                    return null
                }
                return (
                    <span
                        key={point.key}
                        className="absolute flex size-3 -translate-x-1/2 -translate-y-1/2 items-center justify-center"
                        style={{ left: `${x}%`, top: `${y}%` }}
                        title={point.hint}
                        data-testid={`${testId}-point-${point.key}`}
                    >
                        <span className="size-1.5 rounded-full bg-accent" />
                    </span>
                )
            })}
        </div>
    )
}
