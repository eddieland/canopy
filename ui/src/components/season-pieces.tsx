import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * The pieces a season's scene (src/components/season-scenes.tsx) is built from: the frame every piece on the floor
 * stands in, and the drawings in the air that more than a shape and a color make.
 */

/** A firework's sparks, round its center: the angle of each, in radians. */
const SPARKS = Array.from({ length: 12 }, (_, i) => (i * Math.PI) / 6)

/** The bands of a rainbow, outside in: each color and its radius. */
const RAINBOW = [
    { color: 'stroke-flair-red', radius: 63 },
    { color: 'stroke-buddy-ghost-pumpkin', radius: 61 },
    { color: 'stroke-flair-yellow', radius: 59 },
    { color: 'stroke-flair-green', radius: 57 },
    { color: 'stroke-flair-blue', radius: 55 },
    { color: 'stroke-flair-purple', radius: 53 },
]

/** A butterfly's left wings, upper and lower, from its body out; the right are the same, mirrored. */
const BUTTERFLY_WINGS = {
    upper: 'M10 8 C7 2 2 1 1.6 4.4 C1.2 7.6 5 9 10 8 Z',
    lower: 'M10 8.4 C6 9 3.4 11.6 4.8 13.8 C6.4 15.6 9 12.6 10 8.4 Z',
}

/** One piece on the floor: a drawing 26 units tall and `width` wide, over its shadow, as tall as the others. */
export function Piece({ width, className, children }: { width: number; className: string; children: ReactNode }) {
    return (
        <svg viewBox={`0 0 ${width} 26`} className={cn('mb-1 h-9 shrink-0', className)}>
            <ellipse cx={width / 2} cy="25" rx={width / 2 - 4} ry="1" className="fill-buddy-pupil opacity-15" />
            {children}
        </svg>
    )
}

/** A firework at `x`, `y`: sparks flying out round its center, which blooms and fades, starting at `pace`. */
export function Firework({
    x,
    y,
    radius,
    color,
    pace,
}: {
    x: number
    y: number
    radius: number
    color: string
    pace?: string
}) {
    const at = (angle: number, out: number) =>
        `${(x + radius * out * Math.cos(angle)).toFixed(2)} ${(y + radius * out * Math.sin(angle)).toFixed(2)}`
    return (
        <g className={cn('animate-buddy-burst', color, pace)}>
            <path
                d={SPARKS.map((angle) => `M${at(angle, 0.35)} L${at(angle, 0.78)}`).join(' ')}
                strokeWidth="1.2"
                strokeLinecap="round"
            />
            {SPARKS.map((angle) => {
                const [cx, cy] = at(angle, 1).split(' ')
                return <circle key={angle} cx={cx} cy={cy} r="0.9" className="stroke-none" />
            })}
            <circle cx={x} cy={y} r="1.2" className="stroke-none" />
        </g>
    )
}

/** A butterfly at `x`, `y`, its wings beating as it bobs, in two colors, starting at `pace`. */
export function Butterfly({
    x,
    y,
    upper,
    lower,
    pace,
}: {
    x: number
    y: number
    upper: string
    lower: string
    pace?: string
}) {
    return (
        <g className={cn('animate-buddy-drift', pace)}>
            <g transform={`translate(${x} ${y}) scale(1.25)`}>
                <g className="animate-buddy-flutter">
                    {['', 'translate(20 0) scale(-1 1)'].map((mirror) => (
                        <g key={mirror} transform={mirror}>
                            <path d={BUTTERFLY_WINGS.upper} className={upper} />
                            <path d={BUTTERFLY_WINGS.lower} className={lower} />
                            <circle cx="4.4" cy="4.8" r="1.1" className="fill-buddy-hat-cloth opacity-70" />
                            <circle cx="6.4" cy="11.6" r="0.7" className="fill-buddy-hat-cloth opacity-70" />
                        </g>
                    ))}
                </g>
                <ellipse cx="10" cy="8.4" rx="0.8" ry="3.6" className="fill-buddy-hat" />
                <path
                    d="M9.6 5 C9 3 8 2.2 7.4 2.4 M10.4 5 C11 3 12 2.2 12.6 2.4"
                    fill="none"
                    strokeWidth="0.4"
                    strokeLinecap="round"
                    className="stroke-buddy-hat"
                />
            </g>
        </g>
    )
}

/**
 * A rainbow coming out of a cloud and down into the pot of gold: its feet on the pot, which stands one piece in from
 * the shamrock, 58 pixels from the scene's left, its coins 26 pixels over the scene's floor.
 */
export function Rainbow() {
    return (
        <svg viewBox="0 0 64 64" className="absolute bottom-6.5 left-0 size-16">
            <g fill="none" strokeWidth="2.1" className="opacity-85">
                {/* Each band starts inside the cloud, 10 across, and comes down to the pot along its circle. */}
                {RAINBOW.map(({ color, radius }) => {
                    const top = (64 - Math.sqrt(radius * radius - 100)).toFixed(2)
                    return (
                        <path key={radius} d={`M10 ${top} A${radius} ${radius} 0 0 1 ${radius} 64`} className={color} />
                    )
                })}
            </g>
            {/* The cloud, outlined faintly so it holds its shape on a pale rail. */}
            <g className="fill-buddy-ghost-facet opacity-40">
                <circle cx="5" cy="11" r="4" />
                <circle cx="11" cy="7.4" r="5.4" />
                <circle cx="17.4" cy="10.8" r="4.4" />
            </g>
            <g className="fill-buddy-ghost-shell">
                <circle cx="5" cy="11.4" r="3.6" />
                <circle cx="17.4" cy="11.2" r="4" />
            </g>
            <g className="fill-buddy-hat-cloth">
                <circle cx="5" cy="10.8" r="3.4" />
                <circle cx="11" cy="7.4" r="5" />
                <circle cx="17.4" cy="10.4" r="3.8" />
                <rect x="5" y="9" width="12.4" height="5" />
            </g>
        </svg>
    )
}
