import { useId } from 'react'
import type { ReactNode } from 'react'

import type { SeasonId } from '@/lib/seasons'
import { cn } from '@/lib/utils'

/**
 * What stands beside Sprig in a season (src/lib/seasons.ts), on the same floor as its keyboard, each piece over a soft
 * shadow: a party popper bursting with confetti, a glossy heart with a smaller one behind, a veined shamrock, a painted
 * egg in the grass, a carved jack-o'-lantern whose candle flickers, a steaming pumpkin pie, or a gift with a bow.
 *
 * Some seasons bring company (`SCENES`). At Halloween a tombstone and a black cat that blinks stand by the
 * jack-o'-lantern, and overhead a cobweb hangs in the corner, a spider lets itself down from it and climbs back, and a
 * bat flaps by. At Thanksgiving a turkey fans its tail beside the pie. What hangs or flies is set only when `aloft`:
 * in a slot too short for Sprig's bubble, Sprig stands over the blocks above, and the air over the floor would cover
 * them. Decoration only, hidden from a screen reader.
 */
export function SeasonDecoration({ id, aloft }: { id: SeasonId; aloft: boolean }) {
    const scene = SCENES[id]
    return (
        <div
            aria-hidden
            data-testid="buddy-season"
            data-season={id}
            className="relative flex items-end gap-0.5 self-stretch"
        >
            <Piece width={28} className="w-10">
                {DRAWINGS[id]}
            </Piece>
            {scene?.floor}
            {aloft && scene?.air !== undefined ? (
                <div data-testid="buddy-season-air" className="pointer-events-none absolute inset-0">
                    {scene.air}
                </div>
            ) : null}
        </div>
    )
}

/** One piece on the floor: a drawing 26 units tall and `width` wide, over its shadow, as tall as the others. */
function Piece({ width, className, children }: { width: number; className: string; children: ReactNode }) {
    return (
        <svg viewBox={`0 0 ${width} 26`} className={cn('mb-1 h-9 shrink-0', className)}>
            <ellipse cx={width / 2} cy="25" rx={width / 2 - 4} ry="1" className="fill-buddy-pupil opacity-15" />
            {children}
        </svg>
    )
}

/** The jack-o'-lantern's carved face: eyes, nose, and a mouth, drawn twice, as the cut wall and the glow inside. */
const FACE = [
    'M7.8 13.6 L11.6 13.6 L10.2 10.2 Z',
    'M16.4 13.6 L20.2 13.6 L17.8 10.2 Z',
    'M13 15.7 L15 15.7 L14 14.1 Z',
    'M7.6 17.2 Q14 19.4 20.4 17.2 Q19 22.6 14 22.8 Q9 22.6 7.6 17.2 Z',
].join(' ')

/** A shamrock's leaflet, pointing up from where the three meet. */
const LEAFLET = 'M14 15 C9 13 8 7 11 6 C13 5.5 14 7 14 8 C14 7 15 5.5 17 6 C20 7 19 13 14 15 Z'
/** The right half of a leaflet, which the light misses. */
const LEAFLET_SHADE = 'M14 15 C19 13 20 7 17 6 C15 5.5 14 7 14 8 Z'

/** A heart, the size of the drawing. */
const HEART = 'M14 24 C6 18 3 14 3 10 A5.5 5.5 0 0 1 14 7.5 A5.5 5.5 0 0 1 25 10 C25 14 22 18 14 24 Z'

/** A four-pointed twinkle of light, centered on 0 0, a unit across each way. */
const TWINKLE = 'M0 -1 Q0.15 -0.15 1 0 Q0.15 0.15 0 1 Q-0.15 0.15 -1 0 Q-0.15 -0.15 0 -1 Z'

/** An egg standing on the floor, wider below its middle. */
const EGG = [
    'M14 4.2 C18.8 4.2 21.6 11.6 21.6 16.6 C21.6 21.4 18.4 24.6 14 24.6',
    'C9.6 24.6 6.4 21.4 6.4 16.6 C6.4 11.6 9.2 4.2 14 4.2 Z',
].join(' ')

/** The confetti a party popper throws: where each piece lands, how it turns, and its color. */
const CONFETTI: readonly (readonly [x: number, y: number, turn: number, color: string])[] = [
    [15.6, 9.4, 20, 'fill-flair-red'],
    [19.4, 11.8, -30, 'fill-flair-cyan'],
    [22.8, 7.6, 50, 'fill-flair-yellow'],
    [17.8, 4.6, -60, 'fill-flair-green'],
    [24.6, 13.2, 10, 'fill-flair-purple'],
    [21.2, 2.6, 35, 'fill-flair-blue'],
    [13.4, 5.8, -15, 'fill-flair-cyan'],
    [25.4, 4.2, -40, 'fill-flair-red'],
]

/** A pie crust's crimped edge: where each pinch sits, round the rim. */
const CRIMPS = Array.from({ length: 22 }, (_, i) => {
    const angle = (i / 22) * 2 * Math.PI
    return [14 + 10 * Math.cos(angle), 14.6 + 3.9 * Math.sin(angle)] as const
})

const DRAWINGS: Record<SeasonId, React.JSX.Element> = {
    newyear: (
        <>
            {/* Streamers curling out of the popper's mouth. */}
            <g fill="none" strokeWidth="0.7" strokeLinecap="round">
                <path
                    d="M11.4 12.6 C12.6 8.4 10.6 6.4 12.2 3.6 C13 2.2 14.6 2.4 14.8 1.4"
                    className="stroke-flair-yellow"
                />
                <path
                    d="M12.4 13.6 C15.8 11.2 17.4 13.6 19.8 10.4 C21.6 8 23.8 9.6 25.2 8.2"
                    className="stroke-flair-cyan"
                />
                <path
                    d="M12 13 C14.6 9.6 17 9.2 18.2 6.6 C19.2 4.4 21.4 5.4 23 3.2"
                    className="stroke-buddy-hat-band"
                />
            </g>
            {CONFETTI.map(([x, y, turn, color]) => (
                <rect
                    key={`${x} ${y}`}
                    x={x - 0.7}
                    y={y - 0.35}
                    width="1.4"
                    height="0.7"
                    transform={`rotate(${turn} ${x} ${y})`}
                    className={color}
                />
            ))}
            <g className="animate-buddy-candle fill-buddy-hat-gold">
                <path d={TWINKLE} transform="translate(20.6 15.8) scale(1.4)" />
                <path d={TWINKLE} transform="translate(9 4.4) scale(1.2)" />
                <path d={TWINKLE} transform="translate(26 10.8) scale(0.9)" />
            </g>
            {/* The popper, a striped cone tipped back on the floor with its mouth to the sky. */}
            <g transform="translate(9.6 14.6) rotate(35)">
                <path d="M-4 0 L0 11 L4 0 Z" className="fill-buddy-hat-band" />
                <g className="fill-buddy-hat-gold">
                    <path d="M-2.91 3 L2.91 3 L2.18 5 L-2.18 5 Z" />
                    <path d="M-1.45 7 L1.45 7 L0.87 8.6 L-0.87 8.6 Z" />
                </g>
                <path d="M0 0 L4 0 L0 11 Z" className="fill-buddy-pupil opacity-20" />
                <path
                    d="M-2.6 1.4 L-0.6 8.4"
                    strokeWidth="0.5"
                    strokeLinecap="round"
                    className="stroke-buddy-eye opacity-50"
                />
                <ellipse rx="4" ry="1.4" className="fill-buddy-hat-gold" />
                <ellipse rx="3.2" ry="0.9" className="fill-buddy-pupil opacity-50" />
            </g>
        </>
    ),
    halloween: (
        <>
            {/* The stem, a curl of vine, and a leaf. */}
            <path
                d="M15.6 2.4 C18 1.3 19.6 3 18.6 4.2 C17.9 5 16.9 4.3 17.5 3.6"
                fill="none"
                strokeWidth="0.6"
                strokeLinecap="round"
                className="stroke-buddy-leaf"
            />
            <path d="M15.2 6.8 C17 4.8 20.4 5 21.6 6.4 C19.6 8 17.2 8 15.2 6.8 Z" className="fill-buddy-leaf" />
            <path
                d="M15.6 6.8 C17.6 6.4 19.4 6.3 21 6.4"
                fill="none"
                strokeWidth="0.4"
                className="stroke-buddy-leaf-shade"
            />
            <path
                d="M12.6 8 C12.4 5.4 13.3 3.2 15.6 1.8 L16.7 3 C15 4.2 14.6 5.8 15.2 8 Z"
                className="fill-buddy-leaf-shade"
            />
            {/* The body, five ribs: the outer two turned away into shade. */}
            <ellipse cx="8" cy="16.3" rx="6.6" ry="8.2" className="fill-buddy-ghost-pumpkin-shade" />
            <ellipse cx="20" cy="16.3" rx="6.6" ry="8.2" className="fill-buddy-ghost-pumpkin-shade" />
            <g strokeWidth="0.5" className="fill-buddy-ghost-pumpkin stroke-buddy-ghost-pumpkin-shade">
                <ellipse cx="10.6" cy="16" rx="6" ry="8.8" />
                <ellipse cx="17.4" cy="16" rx="6" ry="8.8" />
                <ellipse cx="14" cy="15.8" rx="5" ry="9.2" />
            </g>
            <path
                d="M10.4 11.2 Q11.2 8.4 13.6 7.4"
                fill="none"
                strokeWidth="0.9"
                strokeLinecap="round"
                className="stroke-buddy-eye opacity-50"
            />
            {/* The face: the cut wall, then the candlelight inside, set down and in so the wall shows above it. */}
            <path d={FACE} className="fill-buddy-ghost-pumpkin-shade" />
            <g className="animate-buddy-candle">
                <path d={FACE} transform="translate(0.3 0.45)" className="fill-buddy-hat-gold" />
                <ellipse cx="14" cy="20.4" rx="2.2" ry="0.8" className="fill-buddy-hat-cloth opacity-40" />
            </g>
            <g className="fill-buddy-ghost-pumpkin">
                <path d="M10.5 17.6 L12.2 17.9 L11.9 19.7 L10.8 19.5 Z" />
                <path d="M17.5 17.6 L15.8 17.9 L16.1 19.7 L17.2 19.5 Z" />
                <path d="M13 23 L13.4 21.2 L14.6 21.2 L15 23 Z" />
            </g>
        </>
    ),
    winter: (
        <>
            {/* The box, in snowflake paper, under its lid's shadow. */}
            <rect x="4.5" y="11.5" width="19" height="13" rx="1" className="fill-buddy-hat-band" />
            <g className="fill-buddy-hat-cloth opacity-60">
                <circle cx="7.4" cy="16" r="0.7" />
                <circle cx="10.2" cy="21.4" r="0.7" />
                <circle cx="18.2" cy="15.6" r="0.7" />
                <circle cx="21" cy="21" r="0.7" />
                <circle cx="7.6" cy="22.6" r="0.4" />
                <circle cx="20.6" cy="18" r="0.4" />
            </g>
            <path d={TWINKLE} transform="translate(9.6 18.2) scale(1.3)" className="fill-buddy-hat-cloth opacity-60" />
            <path d={TWINKLE} transform="translate(18.6 22.2) scale(1.1)" className="fill-buddy-hat-cloth opacity-60" />
            <rect x="12.6" y="11.5" width="2.8" height="13" className="fill-buddy-hat-gold" />
            <rect x="4.5" y="12.5" width="19" height="1.2" className="fill-buddy-pupil opacity-20" />
            {/* The lid, a little wider than the box, with the ribbon over it. */}
            <rect x="3.5" y="9" width="21" height="3.6" rx="0.8" className="fill-buddy-hat-band" />
            <rect x="4.3" y="9.5" width="19.4" height="0.6" rx="0.3" className="fill-buddy-eye opacity-30" />
            <rect x="12.6" y="9" width="2.8" height="3.6" className="fill-buddy-hat-gold" />
            <rect x="12.6" y="11.6" width="2.8" height="1" className="fill-buddy-ghost-gilt-shade" />
            {/* The bow: two tails, two loops with their insides in shade, and the knot. */}
            <g strokeWidth="0.35" strokeLinejoin="round" className="fill-buddy-hat-gold stroke-buddy-ghost-gilt-shade">
                <path d="M13.2 9.2 L9.4 14 L10.9 13.8 L11.2 15.2 L14.4 9.8 Z" />
                <path d="M14.8 9.2 L18.6 14 L17.1 13.8 L16.8 15.2 L13.6 9.8 Z" />
            </g>
            <g className="fill-buddy-hat-gold">
                <path d="M14 9 C11 3.6 5.2 4.6 6.4 7.4 C7.2 9.2 11 9.4 14 9 Z" />
                <path d="M14 9 C17 3.6 22.8 4.6 21.6 7.4 C20.8 9.2 17 9.4 14 9 Z" />
            </g>
            <g className="fill-buddy-ghost-gilt-shade">
                <path d="M12.9 8.6 C11 5.8 8.1 5.9 8.2 7.2 C8.4 8.3 10.9 8.7 12.9 8.6 Z" />
                <path d="M15.1 8.6 C17 5.8 19.9 5.9 19.8 7.2 C19.6 8.3 17.1 8.7 15.1 8.6 Z" />
            </g>
            <ellipse
                cx="14"
                cy="8.9"
                rx="1.6"
                ry="1.3"
                strokeWidth="0.4"
                className="fill-buddy-hat-gold stroke-buddy-ghost-gilt-shade"
            />
        </>
    ),
    valentines: (
        <>
            {/* A smaller heart behind, tipped over its shoulder. */}
            <path
                d={HEART}
                transform="translate(22.6 6.4) rotate(18) scale(0.4) translate(-14 -14)"
                className="fill-buddy-hat-band"
            />
            <g transform="translate(-1.5 1)">
                <path d={HEART} className="fill-flair-red" />
                <path
                    d="M14 24 C22 18 25 14 25 10 A5.5 5.5 0 0 0 23.4 6.1 C24.4 10.6 21.6 15.8 14 24 Z"
                    className="fill-buddy-pupil opacity-20"
                />
                <ellipse
                    cx="8.2"
                    cy="9.6"
                    rx="2.2"
                    ry="1.2"
                    transform="rotate(-38 8.2 9.6)"
                    className="fill-buddy-eye opacity-60"
                />
                <circle cx="6.2" cy="12.6" r="0.55" className="fill-buddy-eye opacity-60" />
            </g>
            <path d={TWINKLE} transform="translate(3 3) scale(2)" className="fill-buddy-hat-gold" />
        </>
    ),
    spring: <PaintedEgg />,
    harvest: (
        <>
            {/* Steam rising off the pie, still warm. */}
            <g
                fill="none"
                strokeWidth="0.7"
                strokeLinecap="round"
                className="animate-buddy-candle stroke-buddy-ghost-facet opacity-60"
            >
                <path d="M9.6 9.4 C8.4 7.6 10.8 6.4 9.6 4.4" />
                <path d="M14 8.6 C12.8 6.4 15.2 5 14 2.4" />
                <path d="M18.4 9.4 C17.2 7.6 19.6 6.4 18.4 4.4" />
            </g>
            {/* The dish, glazed, a little wider than the pie in it. */}
            <path d="M1.6 15 L3.4 21.4 Q14 26 24.6 21.4 L26.4 15 Z" className="fill-buddy-hat-blue" />
            <path d="M3.4 21.4 Q14 26 24.6 21.4 L25 20 Q14 24.4 3 20 Z" className="fill-buddy-pupil opacity-25" />
            <ellipse cx="14" cy="15" rx="12.4" ry="5" className="fill-buddy-hat-blue" />
            <path d="M3 13.6 Q6 10.6 11 10.2" fill="none" strokeWidth="0.5" className="stroke-buddy-eye opacity-50" />
            {/* The crust, crimped round its rim, and the filling inside it. */}
            <ellipse cx="14" cy="14.6" rx="10.8" ry="4.4" className="fill-buddy-hat-gold" />
            <g className="fill-buddy-hat-gold stroke-buddy-ghost-gilt-shade" strokeWidth="0.35">
                {CRIMPS.map(([x, y]) => (
                    <circle key={`${x} ${y}`} cx={x} cy={y} r="1.2" />
                ))}
            </g>
            <ellipse cx="14" cy="14.8" rx="8.4" ry="3.1" className="fill-buddy-ghost-pumpkin-shade" />
            <ellipse cx="13.4" cy="14.4" rx="7" ry="2.3" className="fill-buddy-ghost-pumpkin" />
            {/* A dollop of cream on top, swirled to a point. */}
            <ellipse cx="14" cy="14.6" rx="2.8" ry="1.2" className="fill-buddy-ghost-shell" />
            <path
                d="M11.6 14.4 C11.4 12.6 16.6 12.6 16.4 14.2 C15.2 15 12.8 15 11.6 14.4 Z"
                className="fill-buddy-hat-cloth"
            />
            <path
                d="M12.6 13.2 C12.8 11.6 15.4 11.8 15 12.6 C14.6 13.6 13.4 13.6 12.6 13.2 Z"
                className="fill-buddy-hat-cloth"
            />
            <path
                d="M13.4 12.2 C13.6 11.2 14.4 10.8 14.8 10.6 C14.8 11.4 14.6 12 14.2 12.4 Z"
                className="fill-buddy-hat-cloth"
            />
        </>
    ),
    shamrock: (
        <>
            <path
                d="M14 15 C14 19 15 22 18 25"
                fill="none"
                strokeWidth="1.5"
                strokeLinecap="round"
                className="stroke-buddy-leaf-shade"
            />
            {[-90, 0, 90].map((turn) => (
                <g key={turn} transform={`rotate(${turn} 14 15)`}>
                    <path d={LEAFLET} strokeWidth="0.5" className="fill-buddy-leaf stroke-buddy-leaf-shade" />
                    <path d={LEAFLET_SHADE} className="fill-buddy-leaf-shade opacity-40" />
                    <path
                        d="M14 14.4 L14 8.6"
                        strokeWidth="0.45"
                        strokeLinecap="round"
                        className="stroke-buddy-leaf-shade"
                    />
                    <path
                        d="M10.4 8.4 Q10.8 6.8 12 6.6"
                        fill="none"
                        strokeWidth="0.6"
                        strokeLinecap="round"
                        className="stroke-buddy-eye opacity-40"
                    />
                </g>
            ))}
            <circle cx="14" cy="15" r="0.9" className="fill-buddy-leaf-shade" />
            <path d={TWINKLE} transform="translate(23.6 3.4) scale(1.8)" className="fill-buddy-hat-gold" />
        </>
    ),
}

/** What a season brings besides its drawing: more on the floor, and what hangs or flies over it. */
interface Scene {
    /** Pieces on the floor beside the season's drawing. */
    floor: React.JSX.Element
    /** What hangs or flies over the floor, set only where Sprig has the room above it. */
    air?: React.JSX.Element
}

/** The spokes of the cobweb in the corner, in degrees from the top edge round toward the side. */
const WEB_SPOKES = [3, 24, 45, 66, 87]

/** A point on the cobweb, `radius` out from the corner along the spoke at `degrees`. */
function webPoint(radius: number, degrees: number): string {
    const angle = (degrees * Math.PI) / 180
    return `${(30 - radius * Math.cos(angle)).toFixed(2)} ${(radius * Math.sin(angle)).toFixed(2)}`
}

/** A cobweb strung in a top-right corner: its spokes, then its rings, each sagging toward the corner between spokes. */
const WEB = [
    ...WEB_SPOKES.map((degrees) => `M30 0 L${webPoint(29, degrees)}`),
    ...[6, 12, 18, 24].map((radius) =>
        [
            `M${webPoint(radius, WEB_SPOKES[0] ?? 0)}`,
            ...WEB_SPOKES.slice(1).map(
                (degrees) => `Q${webPoint(radius * 0.82, degrees - 10.5)} ${webPoint(radius, degrees)}`,
            ),
        ].join(' '),
    ),
].join(' ')

/** One side's four legs of the spider, from its body out; the other side is the same, mirrored. */
const SPIDER_LEGS = [
    'M5 15.6 Q2.6 13.4 1.2 15.2',
    'M5 16.4 Q2.4 15.6 0.8 17.4',
    'M5 17.2 Q2.6 17.6 1.6 19.8',
    'M5.2 17.8 Q3.6 19.2 3.2 21.4',
].join(' ')

/** A bat's left wing, scalloped along its trailing edge, from the body out; the right is the same, mirrored. */
const BAT_WING =
    'M12 6 C10 3 7 2.4 4 3 C3 4 1.6 4.6 0.4 4.4 C1.6 5.6 2 7 2 8.4 C3.2 7.6 4.4 7.8 5.2 8.8 C6 7.8 7.4 7.6 8.6 8.4 Z'

/** A turkey's tail feathers, fanned from behind its body: their angles from upright. */
const FEATHERS = [-72, -48, -24, 0, 24, 48, 72]

const SCENES: Partial<Record<SeasonId, Scene>> = {
    halloween: {
        floor: (
            <>
                <Piece width={18} className="w-6">
                    {/* A tombstone, settled a little crooked, cracked at its shoulder. */}
                    <g transform="rotate(-5 9 25)">
                        <path
                            d="M3 25 L3 10 C3 5 6 3 9 3 C12 3 15 5 15 10 L15 25 Z"
                            className="fill-buddy-ghost-facet"
                        />
                        <path
                            d="M9 3 C12 3 15 5 15 10 L15 25 L12.6 25 L12.6 10 C12.6 6 11 3.6 9 3 Z"
                            className="fill-buddy-pupil opacity-20"
                        />
                        <path
                            d="M4.4 11 C4.4 6.8 6.4 4.6 9 4.4"
                            fill="none"
                            strokeWidth="0.6"
                            strokeLinecap="round"
                            className="stroke-buddy-eye opacity-30"
                        />
                        <text
                            x="8.6"
                            y="13.4"
                            textAnchor="middle"
                            fontSize="4.4"
                            fontWeight="700"
                            className="fill-buddy-pupil opacity-50"
                        >
                            RIP
                        </text>
                        <g strokeWidth="0.6" strokeLinecap="round" className="stroke-buddy-pupil opacity-30">
                            <path d="M5.6 16.4 L11.6 16.4" />
                            <path d="M6.4 18.6 L10.8 18.6" />
                        </g>
                        <path
                            d="M12.6 4.6 L11.6 6.6 L12.8 7.8 L12 9.8"
                            fill="none"
                            strokeWidth="0.45"
                            strokeLinejoin="round"
                            className="stroke-buddy-pupil opacity-50"
                        />
                    </g>
                    <g className="fill-buddy-leaf">
                        <path d="M1.6 25 L2.8 21.6 L4 25 Z" />
                        <path d="M8 25 L9.4 22.6 L10.4 25 Z" />
                        <path d="M14 25 L15.6 21.8 L16.6 25 Z" />
                    </g>
                    <g className="fill-buddy-leaf-shade">
                        <path d="M3.4 25 L5 22.4 L5.6 25 Z" />
                        <path d="M11.4 25 L12.4 23 L13.4 25 Z" />
                    </g>
                </Piece>
                <Piece width={21} className="w-[1.8rem]">
                    {/* A black cat sitting up, its tail curled round, its eyes catching the candlelight. */}
                    <path
                        d="M14 24.4 C19 24.6 19.8 18.4 17.6 15.4 C16.8 14.2 17.6 12.8 18.8 13.6"
                        fill="none"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                        className="stroke-buddy-hat"
                    />
                    <path d="M5 25 C4 20 5.4 15 10 14.4 C14.6 15 16 20 15 25 Z" className="fill-buddy-hat" />
                    <path
                        d="M6 23.6 C5.6 19.8 6.6 16.6 9 15.6"
                        fill="none"
                        strokeWidth="0.5"
                        strokeLinecap="round"
                        className="stroke-buddy-eye opacity-20"
                    />
                    <g className="fill-buddy-hat">
                        <path d="M5.6 9.8 L5.8 4.6 L9 7.4 Z" />
                        <path d="M14.4 9.8 L14.2 4.6 L11 7.4 Z" />
                        <ellipse cx="10" cy="10.8" rx="4.8" ry="4" />
                    </g>
                    <g className="fill-buddy-hat-band opacity-60">
                        <path d="M6.4 8 L6.5 5.8 L8 7.1 Z" />
                        <path d="M13.6 8 L13.5 5.8 L12 7.1 Z" />
                    </g>
                    <g className="animate-buddy-blink">
                        <ellipse cx="8.1" cy="10.4" rx="1.15" ry="1.25" className="fill-buddy-hat-gold" />
                        <ellipse cx="11.9" cy="10.4" rx="1.15" ry="1.25" className="fill-buddy-hat-gold" />
                        <ellipse cx="8.1" cy="10.4" rx="0.3" ry="0.95" className="fill-buddy-pupil" />
                        <ellipse cx="11.9" cy="10.4" rx="0.3" ry="0.95" className="fill-buddy-pupil" />
                    </g>
                    <path d="M9.4 12.2 L10.6 12.2 L10 12.9 Z" className="fill-buddy-hat-band" />
                    <g strokeWidth="0.25" strokeLinecap="round" className="stroke-buddy-ghost-shell opacity-60">
                        <path d="M8.4 12.6 L4.6 12" />
                        <path d="M8.4 13 L4.8 13.6" />
                        <path d="M11.6 12.6 L15.4 12" />
                        <path d="M11.6 13 L15.2 13.6" />
                    </g>
                </Piece>
            </>
        ),
        air: (
            <>
                <svg viewBox="0 0 30 30" className="absolute top-0 right-0 size-10">
                    <path
                        d={WEB}
                        fill="none"
                        strokeWidth="0.4"
                        strokeLinecap="round"
                        className="stroke-buddy-ghost-facet opacity-70"
                    />
                </svg>
                {/* The spider hangs from the web's second ring, on a thread that stretches as it drops. */}
                <svg viewBox="0 0 12 30" className="absolute top-3 right-1 h-10 w-4 overflow-visible">
                    <path d="M6 0 L6 14" strokeWidth="0.3" className="animate-buddy-thread stroke-buddy-ghost-facet" />
                    <g className="animate-buddy-dangle">
                        <g fill="none" strokeWidth="0.6" strokeLinecap="round" className="stroke-buddy-hat">
                            <path d={SPIDER_LEGS} />
                            <path d={SPIDER_LEGS} transform="translate(12 0) scale(-1 1)" />
                        </g>
                        <ellipse cx="6" cy="17.6" rx="2.2" ry="2.5" className="fill-buddy-hat" />
                        <circle cx="6" cy="14.8" r="1.5" className="fill-buddy-hat" />
                        <ellipse cx="5.2" cy="16.8" rx="0.6" ry="0.9" className="fill-buddy-eye opacity-25" />
                        <circle cx="5.4" cy="14.6" r="0.55" className="fill-buddy-eye" />
                        <circle cx="6.6" cy="14.6" r="0.55" className="fill-buddy-eye" />
                        <circle cx="5.5" cy="14.75" r="0.25" className="fill-buddy-pupil" />
                        <circle cx="6.7" cy="14.75" r="0.25" className="fill-buddy-pupil" />
                    </g>
                </svg>
                <svg viewBox="0 0 24 12" className="animate-buddy-drift absolute top-3 left-1 h-4 w-8">
                    <g className="animate-buddy-flap fill-buddy-hat">
                        <path d={BAT_WING} />
                        <path d={BAT_WING} transform="translate(24 0) scale(-1 1)" />
                    </g>
                    <g className="fill-buddy-hat">
                        <ellipse cx="12" cy="6.8" rx="1.8" ry="2.6" />
                        <circle cx="12" cy="4.2" r="1.6" />
                        <path d="M10.8 3.4 L11 1.6 L11.8 2.8 Z" />
                        <path d="M13.2 3.4 L13 1.6 L12.2 2.8 Z" />
                    </g>
                    <circle cx="11.4" cy="4.1" r="0.35" className="fill-buddy-hat-gold" />
                    <circle cx="12.6" cy="4.1" r="0.35" className="fill-buddy-hat-gold" />
                </svg>
            </>
        ),
    },
    harvest: {
        floor: (
            <Piece width={26} className="w-9">
                {/* A turkey, its tail fanned behind it in three bands, gold at the tips. */}
                {[
                    { length: 11, width: 2.6, color: 'fill-buddy-hat-gold' },
                    { length: 9.2, width: 2.4, color: 'fill-buddy-ghost-pumpkin-shade' },
                    { length: 7.2, width: 2.2, color: 'fill-buddy-ghost-vex-shade' },
                ].map(({ length, width, color }) => (
                    <g key={length} className={color}>
                        {FEATHERS.map((turn) => (
                            <ellipse
                                key={turn}
                                cx="13"
                                cy={17 - length / 2}
                                rx={width}
                                ry={length / 2}
                                transform={`rotate(${turn} 13 17)`}
                            />
                        ))}
                    </g>
                ))}
                <g strokeWidth="0.6" strokeLinecap="round" className="stroke-buddy-hat-gold">
                    <path d="M11.4 22.6 L11 25 M11 25 L10 25.2 M11 25 L11.8 25.2" />
                    <path d="M14.6 22.6 L15 25 M15 25 L14.2 25.2 M15 25 L16 25.2" />
                </g>
                <ellipse cx="13" cy="18.4" rx="5" ry="5.2" className="fill-buddy-ghost-vex-shade" />
                <ellipse cx="13" cy="19.2" rx="3.2" ry="3.6" className="fill-buddy-ghost-vex" />
                <path
                    d="M11 11.6 C11 14 11.4 15.6 13 15.6 C14.6 15.6 15 14 15 11.6 Z"
                    className="fill-buddy-ghost-vex-shade"
                />
                <circle cx="13" cy="11" r="2.6" className="fill-buddy-ghost-vex" />
                <circle cx="12" cy="10.4" r="0.7" className="fill-buddy-eye" />
                <circle cx="14" cy="10.4" r="0.7" className="fill-buddy-eye" />
                <circle cx="12.1" cy="10.5" r="0.35" className="fill-buddy-pupil" />
                <circle cx="14.1" cy="10.5" r="0.35" className="fill-buddy-pupil" />
                <path d="M12.2 11.6 L13.8 11.6 L13 13 Z" className="fill-buddy-hat-gold" />
                <path
                    d="M13.5 12.4 C14.6 13.2 14.5 15 13.5 15.2 C12.9 14.4 13.1 13.2 13.5 12.4 Z"
                    className="fill-flair-red"
                />
            </Piece>
        ),
    },
}

/**
 * A painted egg standing in the grass, banded with a zigzag and dotted, beside a daisy. A component of its own, since
 * its bands are clipped to its shell by an id each drawing must not share with another.
 */
function PaintedEgg() {
    const shell = useId()
    return (
        <>
            <clipPath id={shell}>
                <path d={EGG} />
            </clipPath>
            <path d={EGG} className="fill-buddy-ghost-eye" />
            <g clipPath={`url(#${shell})`}>
                <rect x="4" y="9.6" width="20" height="1.6" className="fill-buddy-hat-gold" />
                <path
                    d="M4 15.2 L6 13.2 L8 15.2 L10 13.2 L12 15.2 L14 13.2 L16 15.2 L18 13.2 L20 15.2 L22 13.2 L24 15.2"
                    fill="none"
                    strokeWidth="1.3"
                    strokeLinejoin="round"
                    className="stroke-buddy-hat-band"
                />
                <rect x="4" y="18.4" width="20" height="2.4" className="fill-buddy-hat-cloth" />
                <g className="fill-buddy-hat-band">
                    <circle cx="9.6" cy="7.4" r="0.6" />
                    <circle cx="14" cy="6.6" r="0.6" />
                    <circle cx="18.4" cy="7.4" r="0.6" />
                </g>
                <g className="fill-buddy-hat-band">
                    <circle cx="9" cy="19.6" r="0.5" />
                    <circle cx="12" cy="19.6" r="0.5" />
                    <circle cx="15" cy="19.6" r="0.5" />
                    <circle cx="18" cy="19.6" r="0.5" />
                </g>
                {/* The side away from the light, then a gleam on the near one. */}
                <path d="M17 3 C23 6 24.4 19 18 26 L26 26 L26 3 Z" className="fill-buddy-pupil opacity-15" />
            </g>
            <path d={EGG} fill="none" strokeWidth="0.4" className="stroke-buddy-pupil opacity-20" />
            <ellipse
                cx="10.4"
                cy="9.8"
                rx="1.1"
                ry="2.2"
                transform="rotate(20 10.4 9.8)"
                className="fill-buddy-eye opacity-60"
            />
            {/* Grass round its foot. */}
            <g className="fill-buddy-leaf">
                <path d="M3 25 L4.2 20.4 L5.4 25 Z" />
                <path d="M6 25 L8 21.4 L8.6 25 Z" />
                <path d="M18.6 25 L20.4 21.6 L21.4 25 Z" />
                <path d="M11 25 L12.4 22.6 L13.6 25 Z" />
            </g>
            <g className="fill-buddy-leaf-shade">
                <path d="M4.6 25 L6.4 21.8 L7 25 Z" />
                <path d="M15.4 25 L16.4 22.4 L17.6 25 Z" />
                <path d="M21 25 L22 22.8 L23.2 25 Z" />
            </g>
            {/* A daisy beside it. */}
            <path
                d="M24.4 25 C24.4 22.4 25 20.6 24.6 18.6"
                fill="none"
                strokeWidth="0.6"
                strokeLinecap="round"
                className="stroke-buddy-leaf-shade"
            />
            <g strokeWidth="0.25" className="fill-buddy-hat-cloth stroke-buddy-ghost-facet">
                {[0, 60, 120, 180, 240, 300].map((turn) => (
                    <ellipse key={turn} cx="24.6" cy="16.6" rx="0.6" ry="1.2" transform={`rotate(${turn} 24.6 18)`} />
                ))}
            </g>
            <circle cx="24.6" cy="18" r="0.75" className="fill-buddy-hat-gold" />
        </>
    )
}
