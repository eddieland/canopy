import { burstWord } from '@/lib/burst'
import { cn } from '@/lib/utils'

// How far each of the plate's spikes reaches, as a share of its half width, round the plate: uneven, as a letterer
// cuts one by hand. Between each pair a notch sits at `NOTCH`.
const SPIKES = [1, 0.9, 0.98, 0.86, 1, 0.92, 0.97, 0.88, 1, 0.9, 0.96, 0.87, 0.99, 0.91]
const NOTCH = 0.7

// The plate's outline in a 100 by 100 box, stretched to its word's width.
const PLATE = SPIKES.flatMap((reach, n) => {
    const spike = (n / SPIKES.length) * 2 * Math.PI
    const notch = ((n + 0.5) / SPIKES.length) * 2 * Math.PI
    return [point(spike, reach), point(notch, NOTCH)]
}).join(' ')

/**
 * A comic's starburst, the bang a cleared attention item goes off with where the palette shows it in place of the leaf
 * (ui/DESIGN.md, "Fun"): a jagged process-yellow plate lettered with a sound effect picked by the item's `id`, once, as
 * it mounts. It shows only where `--burst-plate` says so, so it never knows which palette it is on. Place it with
 * `className`, absolutely, over room it may take: it takes no pointer, is hidden from a screen reader, and under
 * reduced motion is not shown at all.
 */
export function Starburst({ id, className }: { id: string; className?: string }) {
    return (
        <span
            aria-hidden
            data-testid="starburst"
            className={cn('pointer-events-none absolute burst-plate motion-reduce:hidden', className)}
        >
            <span className="relative grid animate-burst place-items-center px-6 py-3.5">
                <svg
                    viewBox="0 0 100 100"
                    preserveAspectRatio="none"
                    className="absolute inset-0 size-full overflow-visible burst-drop"
                >
                    <polygon
                        points={PLATE}
                        strokeWidth={2}
                        strokeLinejoin="miter"
                        vectorEffect="non-scaling-stroke"
                        className="fill-flair-burst stroke-flair-burst-line"
                    />
                </svg>
                <span
                    className={cn(
                        'relative -skew-x-8 text-sm leading-none font-semibold tracking-wide whitespace-nowrap',
                        'text-flair-burst-letter uppercase burst-word',
                    )}
                >
                    {burstWord(id)}
                </span>
            </span>
        </span>
    )
}

function point(angle: number, reach: number): string {
    const x = 50 + 50 * reach * Math.cos(angle)
    const y = 50 + 50 * reach * Math.sin(angle)
    return `${x.toFixed(1)},${y.toFixed(1)}`
}
