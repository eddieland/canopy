import { Cobweb, Spider } from '@/components/season-pieces'
import type { SeasonId } from '@/lib/seasons'
import { cn } from '@/lib/utils'

/**
 * What a season hangs over the header's logo (src/lib/seasons.ts), in the logo's own box: at Halloween a cobweb strung
 * across it from the header's corner, a spider resting at its edge; in winter, from the day after Thanksgiving, a
 * string of lights swagged over it, twinkling. Other seasons leave it bare. Decoration only: it takes no pointer, and
 * a screen reader skips it.
 */
export function LogoDecoration({ id }: { id: SeasonId }) {
    const over = OVER_LOGO[id]
    return over === null ? null : (
        <span aria-hidden data-testid="logo-season" data-season={id} className="pointer-events-none absolute inset-0">
            {over}
        </span>
    )
}

/** A point on a quadratic curve from `from` to `to`, bent toward `bend`, `t` of the way along. */
function along(from: Point, bend: Point, to: Point, t: number): Point {
    const u = 1 - t
    return [
        u * u * from[0] + 2 * u * t * bend[0] + t * t * to[0],
        u * u * from[1] + 2 * u * t * bend[1] + t * t * to[1],
    ]
}

/** A point in a drawing, across and down. */
type Point = readonly [x: number, y: number]

/** The lights' wire, two swags across the logo: each one's ends and the point it sags toward. */
const SWAGS: readonly (readonly [from: Point, bend: Point, to: Point])[] = [
    [
        [2, 3],
        [25, 11],
        [48, 4],
    ],
    [
        [48, 4],
        [71, 11],
        [94, 3],
    ],
]

/** The bulbs' colors, in the order they hang along the wire. */
const BULB_COLORS = [
    'fill-flair-red',
    'fill-flair-yellow',
    'fill-flair-green',
    'fill-flair-cyan',
    'fill-buddy-hat-band',
    'fill-flair-blue',
]

/** When each bulb twinkles, in the order they hang, so neighbors never dim together. */
const BULB_PACES = [
    '',
    '[animation-delay:-0.8s]',
    '[animation-delay:-0.3s]',
    '[animation-delay:-1.2s]',
    '[animation-delay:-0.5s]',
    '[animation-delay:-1s]',
]

/** Where each bulb hangs: a quarter, half, and three quarters along each swag. */
const BULBS = SWAGS.flatMap(([from, bend, to]) => [0.22, 0.5, 0.78].map((t) => along(from, bend, to, t)))

const OVER_LOGO: Record<SeasonId, React.JSX.Element | null> = {
    newyear: null,
    valentines: null,
    shamrock: null,
    spring: null,
    halloween: (
        <>
            {/* The header's top-left corner is 12 up and 16 left of the logo's box. */}
            <Cobweb className="absolute -top-3 -left-4 size-14 -scale-x-100" />
            <svg viewBox="0 10 12 12" className="absolute -top-3 left-6 size-3">
                <Spider />
            </svg>
        </>
    ),
    harvest: null,
    winter: (
        <svg viewBox="0 0 96 16" className="absolute -top-2.5 -left-1.5 h-4 w-24 overflow-visible">
            <path
                d={SWAGS.map(([from, bend, to]) => `M${from.join(' ')} Q${bend.join(' ')} ${to.join(' ')}`).join(' ')}
                fill="none"
                strokeWidth="0.7"
                strokeLinecap="round"
                className="stroke-buddy-leaf-shade"
            />
            {BULBS.map(([x, y], i) => (
                <g
                    key={`${x} ${y}`}
                    className={cn('animate-buddy-twinkle', BULB_COLORS[i % BULB_COLORS.length], BULB_PACES[i % 6])}
                >
                    <circle cx={x} cy={y + 3.6} r="3.4" className="opacity-25" />
                    <ellipse cx={x} cy={y + 3.4} rx="1.6" ry="2.3" />
                    <circle cx={x - 0.5} cy={y + 2.8} r="0.45" className="fill-buddy-eye opacity-60" />
                    <rect x={x - 0.8} y={y - 0.2} width="1.6" height="1.4" rx="0.3" className="fill-buddy-hat" />
                </g>
            ))}
        </svg>
    ),
}
