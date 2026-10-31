import { Butterfly, Firework, Piece, Rainbow } from '@/components/season-pieces'
import type { SeasonId } from '@/lib/seasons'
import { cn } from '@/lib/utils'

/** A heart, the size of a season's drawing. */
export const HEART = 'M14 24 C6 18 3 14 3 10 A5.5 5.5 0 0 1 14 7.5 A5.5 5.5 0 0 1 25 10 C25 14 22 18 14 24 Z'

/** A four-pointed twinkle of light, centered on 0 0, a unit across each way. */
export const TWINKLE = 'M0 -1 Q0.15 -0.15 1 0 Q0.15 0.15 0 1 Q-0.15 0.15 -1 0 Q-0.15 -0.15 0 -1 Z'

/** A five-pointed star, centered on 0 0, a unit from its center to each point. */
const STAR = `M${Array.from({ length: 10 }, (_, i) => {
    const radius = i % 2 === 0 ? 1 : 0.45
    const angle = ((i * 36 - 90) * Math.PI) / 180
    return `${(radius * Math.cos(angle)).toFixed(3)} ${(radius * Math.sin(angle)).toFixed(3)}`
}).join(' L')} Z`

/** A bud vase, narrow at its neck, round at its foot. */
const VASE = [
    'M4.2 25 C2.8 25 2.6 22.2 3.6 20.4 C4.4 19 4.7 17.6 4.7 16.6',
    'L7.3 16.6 C7.3 17.6 7.6 19 8.4 20.4 C9.4 22.2 9.2 25 7.8 25 Z',
].join(' ')

/** The hearts floating up at Valentine's: where each starts, its size, its color, and its pace. */
const FLOATING_HEARTS = [
    { x: 10, y: 50, size: 0.4, color: 'fill-flair-red', pace: '' },
    { x: 30, y: 30, size: 0.3, color: 'fill-buddy-hat-band', pace: '[animation-delay:-1.4s]' },
    { x: 48, y: 52, size: 0.46, color: 'fill-flair-red', pace: '[animation-delay:-2.6s] [animation-duration:4.6s]' },
    {
        x: 66,
        y: 22,
        size: 0.34,
        color: 'fill-buddy-hat-band',
        pace: '[animation-delay:-0.8s] [animation-duration:3.6s]',
    },
    { x: 84, y: 44, size: 0.4, color: 'fill-flair-red', pace: '[animation-delay:-3.2s]' },
    {
        x: 102,
        y: 26,
        size: 0.28,
        color: 'fill-buddy-hat-band',
        pace: '[animation-delay:-2s] [animation-duration:4.4s]',
    },
    { x: 20, y: 14, size: 0.26, color: 'fill-flair-red', pace: '[animation-delay:-3.6s] [animation-duration:3.8s]' },
]

/** A maple leaf, centered on 0 0, its five lobes jagged. */
const MAPLE = [
    'M0 -4.4 L1.1 -1.8 L3.6 -2.8 L2.8 -0.4 L4.4 0.4 L1.8 1.6 L2.2 3.2 L0.4 2.4 L0 4.6',
    'L-0.4 2.4 L-2.2 3.2 L-1.8 1.6 L-4.4 0.4 L-2.8 -0.4 L-3.6 -2.8 L-1.1 -1.8 Z',
].join(' ')

/** A plain leaf, centered on 0 0, pointed at both ends. */
const LEAF = 'M0 -4.2 C3 -2.4 3 2.2 0 4.4 C-3 2.2 -3 -2.4 0 -4.2 Z'

/** The leaves falling at Thanksgiving: where each starts, its shape, its color, and its pace. */
const LEAVES = [
    { x: 12, y: 18, shape: MAPLE, color: 'fill-buddy-ghost-pumpkin', pace: '' },
    { x: 38, y: 4, shape: LEAF, color: 'fill-flair-red', pace: '[animation-delay:-2.2s] [animation-duration:7s]' },
    {
        x: 64,
        y: 26,
        shape: MAPLE,
        color: 'fill-buddy-hat-gold',
        pace: '[animation-delay:-4s] [animation-duration:6.6s]',
    },
    {
        x: 90,
        y: 10,
        shape: LEAF,
        color: 'fill-buddy-ghost-pumpkin-shade',
        pace: '[animation-delay:-1s] [animation-duration:5.4s]',
    },
    { x: 102, y: 34, shape: MAPLE, color: 'fill-flair-red', pace: '[animation-delay:-3.4s] [animation-duration:7.4s]' },
]

/** A six-armed snowflake, centered on 0 0, a unit from its center to each arm's tip. */
const FLAKE = [
    'M0 -1 L0 1 M-0.87 -0.5 L0.87 0.5 M-0.87 0.5 L0.87 -0.5',
    'M-0.3 -0.8 L0 -0.55 L0.3 -0.8 M-0.3 0.8 L0 0.55 L0.3 0.8',
].join(' ')

/** The snow falling in winter: where each flake starts, its size (a bare dot when 0), and its pace. */
const SNOW = [
    { x: 8, y: 10, size: 2.6, pace: '' },
    { x: 22, y: 30, size: 0, pace: '[animation-delay:-1.6s] [animation-duration:7s]' },
    { x: 34, y: 6, size: 2, pace: '[animation-delay:-3s] [animation-duration:8s]' },
    { x: 48, y: 22, size: 0, pace: '[animation-delay:-0.6s] [animation-duration:5.4s]' },
    { x: 60, y: 40, size: 2.4, pace: '[animation-delay:-4.4s] [animation-duration:7.4s]' },
    { x: 72, y: 12, size: 0, pace: '[animation-delay:-2.4s] [animation-duration:6.4s]' },
    { x: 84, y: 28, size: 2.2, pace: '[animation-delay:-5s]' },
    { x: 96, y: 8, size: 0, pace: '[animation-delay:-3.6s] [animation-duration:7.6s]' },
    { x: 106, y: 36, size: 1.8, pace: '[animation-delay:-1s] [animation-duration:5.8s]' },
]

/** The lights strung round the tree: where each hangs, its color, and when it twinkles. */
const TREE_LIGHTS = [
    { x: 4.6, y: 21.2, color: 'fill-flair-red', pace: '' },
    { x: 8.2, y: 22.4, color: 'fill-flair-yellow', pace: '[animation-delay:-0.4s]' },
    { x: 11.8, y: 21.9, color: 'fill-flair-cyan', pace: '[animation-delay:-0.8s]' },
    { x: 14.8, y: 20.4, color: 'fill-buddy-hat-band', pace: '[animation-delay:-1.2s]' },
    { x: 6, y: 16.2, color: 'fill-flair-cyan', pace: '[animation-delay:-0.2s]' },
    { x: 9.4, y: 16.9, color: 'fill-buddy-hat-band', pace: '[animation-delay:-0.6s]' },
    { x: 12.6, y: 15.6, color: 'fill-flair-yellow', pace: '[animation-delay:-1s]' },
    { x: 7.4, y: 11.4, color: 'fill-flair-red', pace: '[animation-delay:-0.3s]' },
    { x: 10.8, y: 10.8, color: 'fill-flair-cyan', pace: '[animation-delay:-0.9s]' },
]

/** A bunny's left ear, standing up from its head; the right is the same, mirrored. */
const BUNNY_EAR = 'M6.6 10.4 C5 6 5.2 1.8 6.8 1.6 C8.4 1.6 8.6 6 8 10 Z'
/** The pink inside of a bunny's left ear. */
const BUNNY_EAR_INSIDE = 'M6.9 9 C6 6 6.2 3.2 6.9 3 C7.6 3 7.7 6 7.5 8.8 Z'

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

/** What a season brings besides its drawing: more on the floor, and what hangs or flies over it. */
export interface Scene {
    /** Pieces on the floor beside the season's drawing. */
    floor: React.JSX.Element
    /** What hangs or flies over the floor, set only where Sprig has the room above it. */
    air: React.JSX.Element
}

/**
 * Each season's company beside its drawing (src/components/season.tsx). The air is drawn in an SVG whose units are
 * pixels, so a keyframe's `translateY` in index.css moves a piece as far as it says.
 */
export const SCENES: Record<SeasonId, Scene> = {
    newyear: {
        floor: (
            <>
                <Piece width={12} className="w-4">
                    {/* A bottle of bubbly, foil on its neck, foam spilling over its mouth. */}
                    <path
                        d="M3 25 L3 13.4 C3 11 4.4 10 4.8 8.4 L4.8 4.4 L7.2 4.4 L7.2 8.4 C7.6 10 9 11 9 13.4 L9 25 Z"
                        className="fill-buddy-leaf-shade"
                    />
                    <path
                        d="M7.2 8.4 C7.6 10 9 11 9 13.4 L9 25 L7.6 25 L7.6 13.4 C7.6 11.4 7 10 6.6 8.4 Z"
                        className="fill-buddy-pupil opacity-25"
                    />
                    <path d="M4.6 3.8 L7.4 3.8 L7.4 8.6 C6.6 9.2 5.4 9.2 4.6 8.6 Z" className="fill-buddy-hat-gold" />
                    <rect x="3" y="15" width="6" height="5.4" className="fill-buddy-hat-cloth" />
                    <g className="fill-buddy-hat-gold">
                        <rect x="3" y="16" width="6" height="0.6" />
                        <rect x="3" y="18.8" width="6" height="0.6" />
                    </g>
                    <path
                        d="M4 23.6 L4 13.6 C4 12.4 4.6 11.4 5.2 10.6"
                        fill="none"
                        strokeWidth="0.6"
                        strokeLinecap="round"
                        className="stroke-buddy-eye opacity-40"
                    />
                    <g strokeWidth="0.25" className="fill-buddy-hat-cloth stroke-buddy-ghost-facet">
                        <path d="M7.3 3.4 C8.2 5 8 6.6 7.7 7.8 C7.2 6.6 7 5 7.3 3.4 Z" />
                        <circle cx="4.6" cy="3.4" r="1" />
                        <circle cx="7.4" cy="3.1" r="1.1" />
                        <circle cx="6" cy="2.4" r="1.5" />
                    </g>
                </Piece>
                <Piece width={10} className="w-3.5">
                    {/* A flute of it, bubbles rising. */}
                    <path
                        d="M2.6 2.6 L7.4 2.6 L7.2 11.6 C7 13.8 6 15 5 15 C4 15 3 13.8 2.8 11.6 Z"
                        className="fill-buddy-ghost-core opacity-30"
                    />
                    <path
                        d="M3 6.4 L7 6.4 L6.8 11.6 C6.6 13.4 5.8 14.4 5 14.4 C4.2 14.4 3.4 13.4 3.2 11.6 Z"
                        className="fill-buddy-hat-gold"
                    />
                    <g className="fill-buddy-hat-cloth">
                        <circle cx="4.4" cy="12" r="0.4" className="animate-buddy-rise" />
                        <circle cx="5.6" cy="10.4" r="0.35" className="animate-buddy-rise [animation-delay:-0.6s]" />
                        <circle cx="5" cy="8.6" r="0.3" className="animate-buddy-rise [animation-delay:-1.2s]" />
                    </g>
                    <path
                        d="M2.6 2.6 L7.4 2.6 L7.2 11.6 C7 13.8 6 15 5 15 C4 15 3 13.8 2.8 11.6 Z"
                        fill="none"
                        strokeWidth="0.4"
                        className="stroke-buddy-ghost-facet"
                    />
                    <path
                        d="M3.5 3.6 L3.7 10.8"
                        strokeWidth="0.5"
                        strokeLinecap="round"
                        className="stroke-buddy-eye opacity-50"
                    />
                    <path d="M5 15 L5 23.8" strokeWidth="0.7" className="stroke-buddy-ghost-facet" />
                    <ellipse cx="5" cy="24.2" rx="2.8" ry="0.7" className="fill-buddy-ghost-facet" />
                </Piece>
            </>
        ),
        air: (
            <svg viewBox="0 0 112 64" className="absolute top-0 left-0 h-16 w-28">
                {/* Fireworks blooming in turn, with stars about them. */}
                <Firework x={22} y={24} radius={14} color="fill-flair-yellow stroke-flair-yellow" />
                <Firework
                    x={60}
                    y={16}
                    radius={12}
                    color="fill-flair-cyan stroke-flair-cyan"
                    pace="[animation-delay:-0.9s]"
                />
                <Firework
                    x={92}
                    y={36}
                    radius={10}
                    color="fill-buddy-hat-band stroke-buddy-hat-band"
                    pace="[animation-delay:-1.8s]"
                />
                <g className="fill-buddy-hat-gold">
                    <path d={TWINKLE} transform="translate(44 40) scale(2.4)" className="animate-buddy-twinkle" />
                    <path
                        d={TWINKLE}
                        transform="translate(80 6) scale(1.8)"
                        className="animate-buddy-twinkle [animation-delay:-0.5s]"
                    />
                    <path
                        d={TWINKLE}
                        transform="translate(6 48) scale(1.6)"
                        className="animate-buddy-twinkle [animation-delay:-1.1s]"
                    />
                </g>
            </svg>
        ),
    },
    valentines: {
        floor: (
            <>
                <Piece width={12} className="w-4">
                    {/* A single rose in a bud vase, its stem showing through the glass. */}
                    <path
                        d="M6 22 C6 16 6.4 11 6 7.6"
                        fill="none"
                        strokeWidth="0.8"
                        strokeLinecap="round"
                        className="stroke-buddy-leaf-shade"
                    />
                    <path
                        d="M6.2 13.6 C8 11.6 10 12 10.6 12.6 C9.4 14.2 7.6 14.4 6.2 13.6 Z"
                        className="fill-buddy-leaf"
                    />
                    <path d="M6 15.8 C4.4 14.2 2.4 14.4 1.8 15 C3 16.4 4.6 16.6 6 15.8 Z" className="fill-buddy-leaf" />
                    <path
                        d={VASE}
                        strokeWidth="0.4"
                        className="fill-buddy-ghost-core stroke-buddy-ghost-facet opacity-70"
                    />
                    <path
                        d="M3.8 23.6 C3.4 22.4 3.8 21.2 4.4 20.4"
                        fill="none"
                        strokeWidth="0.5"
                        strokeLinecap="round"
                        className="stroke-buddy-eye opacity-60"
                    />
                    <path d="M4.4 8.6 L6 7.4 L7.6 8.6 L6 9.6 Z" className="fill-buddy-leaf-shade" />
                    <path
                        d="M2.8 5.4 C2.8 2.6 9.2 2.6 9.2 5.4 C9.2 7.8 7.8 9 6 9 C4.2 9 2.8 7.8 2.8 5.4 Z"
                        className="fill-flair-red"
                    />
                    <path d="M3.2 4.4 L4.2 2 L6 3.4 L7.8 2 L8.8 4.4 Z" className="fill-flair-red" />
                    <g fill="none" strokeLinecap="round" className="stroke-buddy-pupil">
                        <path
                            d="M6 3.8 C7.6 3.8 7.8 5.8 6.2 6.2 C4.8 6.4 4.4 4.8 5.4 4.4"
                            strokeWidth="0.45"
                            className="opacity-35"
                        />
                        <path d="M3.2 5.6 C3.6 7.6 5 8.4 6.4 8.4" strokeWidth="0.4" className="opacity-25" />
                    </g>
                </Piece>
                <Piece width={16} className="w-5.5">
                    {/* A love letter leaning back, sealed with a heart. */}
                    <g transform="rotate(-8 8 24)">
                        <rect
                            x="1.6"
                            y="14"
                            width="13"
                            height="10"
                            rx="0.6"
                            strokeWidth="0.35"
                            className="fill-buddy-hat-cloth stroke-buddy-ghost-facet"
                        />
                        <path
                            d="M1.8 23.6 L6.4 18.6 M14.4 23.6 L9.8 18.6"
                            fill="none"
                            strokeWidth="0.3"
                            className="stroke-buddy-ghost-facet opacity-60"
                        />
                        <path
                            d="M1.8 14.4 L8.1 19.6 L14.4 14.4"
                            fill="none"
                            strokeWidth="0.4"
                            strokeLinejoin="round"
                            className="stroke-buddy-ghost-facet"
                        />
                        <path
                            d={HEART}
                            transform="translate(8.1 19.6) scale(0.22) translate(-14 -15)"
                            className="fill-flair-red"
                        />
                    </g>
                </Piece>
            </>
        ),
        air: (
            <svg viewBox="0 0 112 64" className="absolute top-0 left-0 h-16 w-28">
                {/* Little hearts floating up, each at a pace of its own. */}
                {FLOATING_HEARTS.map(({ x, y, size, color, pace }) => (
                    <g key={x} className={cn('animate-buddy-float', pace)}>
                        <path
                            d={HEART}
                            transform={`translate(${x} ${y}) scale(${size}) translate(-14 -14)`}
                            className={color}
                        />
                    </g>
                ))}
            </svg>
        ),
    },
    shamrock: {
        floor: (
            <>
                <Piece width={23} className="w-8">
                    {/* A pot of gold, heaped over its rim, glinting. */}
                    <path d="M3.4 13 C4.6 8.8 8 7 11.5 7 C15 7 18.4 8.8 19.6 13 Z" className="fill-buddy-hat-gold" />
                    <g strokeWidth="0.35" className="fill-buddy-hat-gold stroke-buddy-ghost-gilt-shade">
                        <ellipse cx="8.6" cy="9.2" rx="1.5" ry="0.9" />
                        <ellipse cx="13.6" cy="8.6" rx="1.5" ry="0.9" />
                        <ellipse cx="6.4" cy="11.6" rx="1.5" ry="0.9" />
                        <ellipse cx="11.2" cy="11" rx="1.5" ry="0.9" />
                        <ellipse cx="16.4" cy="11.4" rx="1.5" ry="0.9" />
                    </g>
                    <path
                        d="M2.6 13 C2.2 19.4 5 24.4 11.5 24.4 C18 24.4 20.8 19.4 20.4 13 Z"
                        className="fill-buddy-hat"
                    />
                    <path
                        d="M15.4 13 L20.4 13 C20.8 19.4 18 24.4 11.5 24.4 C15.4 22.4 16.4 18 15.4 13 Z"
                        className="fill-buddy-pupil opacity-30"
                    />
                    <path
                        d="M4.6 15.6 C4.8 19 6.4 21.6 9 22.8"
                        fill="none"
                        strokeWidth="0.7"
                        strokeLinecap="round"
                        className="stroke-buddy-eye opacity-25"
                    />
                    <ellipse
                        cx="11.5"
                        cy="13.2"
                        rx="9.6"
                        ry="1.3"
                        strokeWidth="1.3"
                        className="fill-none stroke-buddy-keyboard"
                    />
                    <g className="fill-buddy-hat">
                        <path d="M5 22.6 L4.2 25 L6.4 25 L7 23.6 Z" />
                        <path d="M18 22.6 L18.8 25 L16.6 25 L16 23.6 Z" />
                    </g>
                    <g className="fill-buddy-hat-gold">
                        <path d={TWINKLE} transform="translate(5 5.4) scale(1.5)" className="animate-buddy-twinkle" />
                        <path
                            d={TWINKLE}
                            transform="translate(18.6 4.6) scale(1.2)"
                            className="animate-buddy-twinkle [animation-delay:-0.8s]"
                        />
                    </g>
                </Piece>
                <Piece width={16} className="w-5.5">
                    {/* A leprechaun's hat, buckled, set down at a tilt. */}
                    <g transform="rotate(8 8 23)">
                        <ellipse cx="8" cy="21.8" rx="7.2" ry="1.9" className="fill-buddy-leaf-shade" />
                        <path
                            d="M4.4 21.6 L5.2 9.4 C7 8.8 9 8.8 10.8 9.4 L11.6 21.6 Z"
                            className="fill-buddy-leaf-shade"
                        />
                        <path
                            d="M9.4 9 C10 9.1 10.4 9.2 10.8 9.4 L11.6 21.6 L10.2 21.8 Z"
                            className="fill-buddy-pupil opacity-20"
                        />
                        <ellipse cx="8" cy="9.3" rx="2.8" ry="0.7" className="fill-buddy-leaf" />
                        <path d="M4.6 18 L11.4 18 L11.6 20.6 L4.4 20.6 Z" className="fill-buddy-hat" />
                        <rect
                            x="6.5"
                            y="17.6"
                            width="3"
                            height="3.4"
                            rx="0.3"
                            strokeWidth="0.7"
                            className="fill-none stroke-buddy-hat-gold"
                        />
                        <path
                            d="M5.9 11 L5.5 16.6"
                            strokeWidth="0.6"
                            strokeLinecap="round"
                            className="stroke-buddy-eye opacity-30"
                        />
                        <path
                            d="M1.6 22.4 Q8 24.6 14.4 22.4"
                            fill="none"
                            strokeWidth="0.5"
                            className="stroke-buddy-leaf opacity-70"
                        />
                    </g>
                </Piece>
            </>
        ),
        air: <Rainbow />,
    },
    spring: {
        floor: (
            <>
                <Piece width={18} className="w-6">
                    {/* A bunny sitting up, ears high, who blinks now and then. */}
                    <g className="fill-buddy-ghost-vex">
                        <path d={BUNNY_EAR} />
                        <path d={BUNNY_EAR} transform="translate(18 0) scale(-1 1)" />
                    </g>
                    <g className="fill-buddy-hat-band opacity-50">
                        <path d={BUNNY_EAR_INSIDE} />
                        <path d={BUNNY_EAR_INSIDE} transform="translate(18 0) scale(-1 1)" />
                    </g>
                    <ellipse cx="9" cy="20.4" rx="5.6" ry="4.8" className="fill-buddy-ghost-vex" />
                    <ellipse cx="9" cy="21.2" rx="3.4" ry="3.2" className="fill-buddy-hat-cloth opacity-70" />
                    <circle cx="9" cy="13.4" r="4.2" className="fill-buddy-ghost-vex" />
                    <path
                        d="M12.4 10.8 C14.4 13 14.4 16.4 12 17.6 C13.4 15.6 13.6 13 12.4 10.8 Z"
                        className="fill-buddy-pupil opacity-15"
                    />
                    <path
                        d="M14.4 17.6 C15.2 20 14.8 23 12.6 24.6 C13.6 22.4 13.8 20 14.4 17.6 Z"
                        className="fill-buddy-pupil opacity-15"
                    />
                    <g className="fill-buddy-ghost-vex-shade">
                        <ellipse cx="6" cy="24.4" rx="2.2" ry="0.9" />
                        <ellipse cx="12" cy="24.4" rx="2.2" ry="0.9" />
                    </g>
                    <g className="animate-buddy-blink">
                        <circle cx="7.4" cy="13" r="0.75" className="fill-buddy-pupil" />
                        <circle cx="10.6" cy="13" r="0.75" className="fill-buddy-pupil" />
                    </g>
                    <circle cx="7.6" cy="12.7" r="0.25" className="fill-buddy-eye" />
                    <circle cx="10.8" cy="12.7" r="0.25" className="fill-buddy-eye" />
                    <g className="fill-buddy-hat-band">
                        <path d="M8.4 14.6 L9.6 14.6 L9 15.3 Z" />
                        <circle cx="6.4" cy="15" r="0.8" className="opacity-25" />
                        <circle cx="11.6" cy="15" r="0.8" className="opacity-25" />
                    </g>
                    <path
                        d="M9 15.3 L9 15.9 M8.2 16.2 Q9 16.6 9.8 16.2"
                        fill="none"
                        strokeWidth="0.3"
                        strokeLinecap="round"
                        className="stroke-buddy-ghost-vex-shade"
                    />
                </Piece>
                <Piece width={10} className="w-3.5">
                    {/* A tulip. */}
                    <path
                        d="M5 25 C5 20 5.2 15 5 11"
                        fill="none"
                        strokeWidth="0.8"
                        strokeLinecap="round"
                        className="stroke-buddy-leaf-shade"
                    />
                    <path d="M5 24.6 C2 21 1.6 16.4 2.2 14 C4 16.4 5 20 5 24.6 Z" className="fill-buddy-leaf" />
                    <path
                        d="M2.4 6 L3.6 8 L5 5.6 L6.4 8 L7.6 6 C7.8 9.6 7 11.6 5 11.6 C3 11.6 2.2 9.6 2.4 6 Z"
                        className="fill-buddy-hat-band"
                    />
                    <path
                        d="M5 5.6 L6.4 8 L7.6 6 C7.8 9.6 7 11.6 5 11.6 C6.2 10.4 6.4 8.4 5 5.6 Z"
                        className="fill-buddy-pupil opacity-20"
                    />
                    <path
                        d="M3.2 8 C3.2 9.4 3.6 10.4 4.2 10.8"
                        fill="none"
                        strokeWidth="0.4"
                        strokeLinecap="round"
                        className="stroke-buddy-eye opacity-50"
                    />
                </Piece>
            </>
        ),
        air: (
            <svg viewBox="0 0 112 64" className="absolute top-0 left-0 h-16 w-28">
                {/* Two butterflies about the place. */}
                <Butterfly x={12} y={16} upper="fill-buddy-hat-gold" lower="fill-buddy-ghost-pumpkin" />
                <Butterfly
                    x={70}
                    y={30}
                    upper="fill-flair-cyan"
                    lower="fill-buddy-hat-blue"
                    pace="[animation-delay:-1.2s]"
                />
            </svg>
        ),
    },
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
            <>
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
                <Piece width={16} className="w-5.5">
                    {/* Two gourds, a gold one behind a small pumpkin. */}
                    <path
                        d="M10.6 15.2 C10.4 13.8 11 12.8 12 12.4"
                        fill="none"
                        strokeWidth="0.7"
                        strokeLinecap="round"
                        className="stroke-buddy-leaf-shade"
                    />
                    <ellipse cx="10.6" cy="19.8" rx="4.2" ry="4.8" className="fill-buddy-hat-gold" />
                    <path
                        d="M10.6 15.2 C8.6 17 8.6 22.6 10.6 24.6 M10.6 15.2 C12.6 17 12.6 22.6 10.6 24.6"
                        fill="none"
                        strokeWidth="0.4"
                        className="stroke-buddy-ghost-gilt-shade"
                    />
                    <path
                        d="M5.6 18.4 C5.4 17.2 5.8 16.4 6.6 16"
                        fill="none"
                        strokeWidth="0.8"
                        strokeLinecap="round"
                        className="stroke-buddy-leaf-shade"
                    />
                    <ellipse cx="5.8" cy="21.6" rx="4.6" ry="3.4" className="fill-buddy-ghost-pumpkin" />
                    <g fill="none" strokeWidth="0.4" className="stroke-buddy-ghost-pumpkin-shade">
                        <ellipse cx="5.8" cy="21.6" rx="2.2" ry="3.4" />
                        <path d="M5.8 18.2 L5.8 25" />
                    </g>
                    <path
                        d="M2.6 20.6 Q3.2 19 4.6 18.6"
                        fill="none"
                        strokeWidth="0.5"
                        strokeLinecap="round"
                        className="stroke-buddy-eye opacity-40"
                    />
                </Piece>
            </>
        ),
        air: (
            <svg viewBox="0 0 112 80" className="absolute top-0 left-0 h-20 w-28">
                {/* Leaves coming down, each rocking as it falls, at a pace and a start of its own. */}
                {LEAVES.map(({ x, y, shape, color, pace }) => (
                    <g key={`${x} ${y}`} className={cn('animate-buddy-fall', pace)}>
                        <g transform={`translate(${x} ${y})`}>
                            <g className="animate-buddy-sway">
                                <path d={shape} className={color} />
                                <path d="M0 -3 L0 4.6" strokeWidth="0.4" className="stroke-buddy-pupil opacity-30" />
                            </g>
                        </g>
                    </g>
                ))}
            </svg>
        ),
    },
    winter: {
        floor: (
            <>
                <Piece width={18} className="w-6">
                    {/* A little tree, strung with lights that twinkle, a star on top. */}
                    <rect x="8" y="21.4" width="2" height="3.4" className="fill-buddy-ghost-vex-shade" />
                    <g className="fill-buddy-leaf">
                        <path d="M1.6 22.4 L9 12.6 L16.4 22.4 Q9 24 1.6 22.4 Z" />
                        <path d="M3.2 17 L9 8.2 L14.8 17 Q9 18.4 3.2 17 Z" />
                        <path d="M4.8 11.8 L9 4.6 L13.2 11.8 Q9 12.8 4.8 11.8 Z" />
                    </g>
                    <g className="fill-buddy-pupil opacity-15">
                        <path d="M9 12.6 L16.4 22.4 Q12.8 23.4 9 23.4 Z" />
                        <path d="M9 8.2 L14.8 17 Q12 17.8 9 17.8 Z" />
                        <path d="M9 4.6 L13.2 11.8 Q11 12.4 9 12.4 Z" />
                    </g>
                    <g
                        fill="none"
                        strokeWidth="0.45"
                        strokeLinecap="round"
                        className="stroke-buddy-hat-gold opacity-80"
                    >
                        <path d="M3.4 20.6 Q9 22.6 14.8 19.4" />
                        <path d="M4.8 15.4 Q9 16.8 13.4 14.2" />
                        <path d="M6.2 10.4 Q9 11.4 12.2 9.6" />
                    </g>
                    {TREE_LIGHTS.map(({ x, y, color, pace }) => (
                        <circle
                            key={`${x} ${y}`}
                            cx={x}
                            cy={y}
                            r="0.7"
                            className={cn('animate-buddy-twinkle', color, pace)}
                        />
                    ))}
                    <path
                        d={STAR}
                        transform="translate(9 3.4) scale(2.4)"
                        strokeWidth="0.15"
                        className="animate-buddy-candle fill-buddy-hat-gold stroke-buddy-ghost-gilt-shade"
                    />
                </Piece>
                <Piece width={16} className="w-5.5">
                    {/* A snowman in a top hat and scarf, waving with a twig. */}
                    <g fill="none" strokeWidth="0.5" strokeLinecap="round" className="stroke-buddy-ghost-vex-shade">
                        <path d="M4.2 18.2 L1.2 15.4 M2 16.2 L0.8 16.6" />
                        <path d="M11.8 18.2 L14.8 15.2 M14 16 L15.2 16" />
                    </g>
                    <g strokeWidth="0.4" className="fill-buddy-hat-cloth stroke-buddy-ghost-facet">
                        <circle cx="8" cy="20.4" r="4.4" />
                        <circle cx="8" cy="13.2" r="3.2" />
                    </g>
                    <path d="M11 18 A4 4 0 0 1 8.6 24.4 A4.6 4.6 0 0 0 11 18 Z" className="fill-buddy-ghost-shell" />
                    <g className="fill-buddy-pupil">
                        <circle cx="7" cy="12.6" r="0.45" />
                        <circle cx="9" cy="12.6" r="0.45" />
                        <circle cx="8" cy="18.6" r="0.5" />
                        <circle cx="8" cy="20.8" r="0.5" />
                        <circle cx="8" cy="23" r="0.5" />
                    </g>
                    <path d="M8 13.5 L11 14.1 L8 14.6 Z" className="fill-buddy-ghost-pumpkin" />
                    <path d="M5 15.4 Q8 16.8 11 15.4 L11 16.7 Q8 18.1 5 16.7 Z" className="fill-flair-red" />
                    <path d="M9.4 16.6 L10.8 20.2 L9.4 20.4 L8.6 17 Z" className="fill-flair-red" />
                    <g className="fill-buddy-hat">
                        <rect x="4.8" y="9.6" width="6.4" height="1" rx="0.3" />
                        <rect x="5.8" y="5.8" width="4.4" height="4.2" />
                    </g>
                    <rect x="5.8" y="8.6" width="4.4" height="0.8" className="fill-flair-red" />
                </Piece>
            </>
        ),
        air: (
            <svg viewBox="0 0 112 80" className="absolute top-0 left-0 h-20 w-28">
                {/* Snow coming down, flakes and dots, each at a pace and a start of its own. */}
                {SNOW.map(({ x, y, size, pace }) => (
                    <g key={`${x} ${y}`} className={cn('animate-buddy-fall', pace)}>
                        {size === 0 ? (
                            <circle cx={x} cy={y} r="1" className="fill-buddy-ghost-eye opacity-70" />
                        ) : (
                            <path
                                d={FLAKE}
                                transform={`translate(${x} ${y}) scale(${size})`}
                                fill="none"
                                strokeWidth={0.7 / size}
                                strokeLinecap="round"
                                className="stroke-buddy-ghost-eye"
                            />
                        )}
                    </g>
                ))}
            </svg>
        ),
    },
}
