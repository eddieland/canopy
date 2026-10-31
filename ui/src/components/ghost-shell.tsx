import type { ShellId } from '@/lib/shells'
import { cn } from '@/lib/utils'

/**
 * The Ghost's shells (src/lib/shells.ts), drawn in the Ghost's own units (`GhostFigure` in
 * src/components/shell/buddy.tsx): four great plates around its eye, four lesser ones behind them on the diagonals,
 * and, for some, a crest on top. Most float around a dark body, the eye's lens set in it, as a Ghost's shell floats
 * around its core. Every plate is lit from the top left, as one object is: a facet turned to the light takes the lit
 * color, one turned away the shaded, and each darkens the further it turns. Each shell is a look: the plates' shape
 * and colors, the ring behind the eye, and the eye's glow and core. `ShellPreview` shows one on its own, for the shop.
 */

/** Where the Ghost's eye sits in its drawing, which its shell turns about. */
const GHOST_CENTER = { x: 24, y: 40 }

/** How a shell looks: its plates' shapes, each part's color class, and what it wears on top. */
interface Look {
    /**
     * One great plate, pointing up from the eye: its lit facet left of the ridge and its shaded one right, or a bent
     * wire drawn as a line.
     */
    plate: { lit: string; shaded: string } | { wire: string }
    /** One lesser plate, behind the great ones on the diagonals: its facets either side of the ridge, or one leaf. */
    spike: { lit: string; shaded: string } | { leaf: string }
    /** The fill of a plate's lit facet, or a wire plate's stroke. */
    lit: string
    /** The fill of a plate's shaded facet, and of a leaf. */
    shaded: string
    /** The outline every plate gets, to stand off a light canvas. */
    edge: string
    /** The ring behind the eye. */
    ring: string
    /**
     * The dark body the plates float around, and the eye's lens in it, with the lens's blades: none for a shell that is
     * not a Ghost's, as Sprig's is not.
     */
    body?: string
    /** The glint of light on the lens's glass, for a shell with a body. */
    glint?: string
    /** The eye's glow and light. */
    eye: string
    /** The eye's bright core, its pupil. */
    core: string
    /** What it wears over the top plate, outside the turning shell: none for most. */
    crest?: React.JSX.Element
}

/** A Generalist Shell's plates: a pyramid seen from the front, notched where the ridge meets the eye. */
const FACETED = {
    plate: { lit: 'M0 -24 L-9 -10 L0 -12.5 Z', shaded: 'M0 -24 L0 -12.5 L9 -10 Z' },
    spike: { lit: 'M0 -20 L-5 -9 L0 -10.5 Z', shaded: 'M0 -20 L0 -10.5 L5 -9 Z' },
}

/** Each shell's look. */
const LOOKS: Record<ShellId, Look> = {
    generalist: {
        ...FACETED,
        lit: 'fill-buddy-ghost-shell',
        shaded: 'fill-buddy-ghost-facet',
        edge: 'stroke-buddy-ghost-facet',
        ring: 'fill-buddy-ghost-housing stroke-buddy-ghost-facet',
        body: 'fill-buddy-ghost-housing',
        glint: 'stroke-buddy-ghost-core',
        eye: 'fill-buddy-ghost-eye',
        core: 'fill-buddy-ghost-core',
    },
    // Sprig, as a Ghost: a paperclip of Sprig's wire for each great plate, its innermost turn on the eye, a leaf
    // between each two, one googly eye in a ring of the same wire, and its sprig growing from the top clip.
    sprig: {
        plate: { wire: 'M-1 -15 V-21 A1 1 0 0 1 1 -21 V-12 A2 2 0 0 1 -3 -12 V-22 A3 3 0 0 1 3 -22 V-15' },
        spike: { leaf: 'M0 -19 C-3.5 -16 -3.5 -11 0 -9 C3.5 -11 3.5 -16 0 -19 Z' },
        lit: 'stroke-muted-foreground',
        shaded: 'fill-buddy-leaf',
        edge: 'stroke-buddy-leaf-shade',
        ring: 'fill-buddy-eye stroke-muted-foreground',
        eye: 'fill-buddy-eye',
        core: 'fill-buddy-pupil',
        crest: (
            <g className="text-buddy-leaf" data-crest="sprig">
                <path
                    d="M24 15 C24 11 25 8 28 6"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                />
                <path d="M28 6 C30 0 38 -1 43 2 C40 7 33 10 28 6 Z" fill="currentColor" fillOpacity="0.85" />
            </g>
        ),
    },
    pumpkin: {
        plate: { lit: 'M0 -23 Q-10 -21 -9 -10 L0 -12.5 Z', shaded: 'M0 -23 L0 -12.5 L9 -10 Q10 -21 0 -23 Z' },
        spike: { lit: 'M0 -19 Q-6 -15 -5 -9 L0 -10.5 Z', shaded: 'M0 -19 L0 -10.5 L5 -9 Q6 -15 0 -19 Z' },
        lit: 'fill-buddy-ghost-pumpkin',
        shaded: 'fill-buddy-ghost-pumpkin-shade',
        edge: 'stroke-buddy-ghost-pumpkin-shade',
        ring: 'fill-buddy-ghost-housing stroke-buddy-ghost-pumpkin-shade',
        body: 'fill-buddy-ghost-housing',
        glint: 'stroke-buddy-hat-cloth',
        eye: 'fill-buddy-hat-gold',
        core: 'fill-buddy-hat-cloth',
        crest: (
            <path
                d="M24 17 C23 13 24 11 27 10"
                fill="none"
                strokeWidth="2.2"
                strokeLinecap="round"
                className="stroke-buddy-leaf-shade"
                data-crest="stem"
            />
        ),
    },
    gilded: {
        ...FACETED,
        lit: 'fill-buddy-hat-gold',
        shaded: 'fill-buddy-ghost-gilt-shade',
        edge: 'stroke-buddy-ghost-gilt-shade',
        ring: 'fill-buddy-ghost-housing stroke-buddy-ghost-gilt-shade',
        body: 'fill-buddy-ghost-housing',
        glint: 'stroke-buddy-ghost-core',
        eye: 'fill-buddy-ghost-eye',
        core: 'fill-buddy-ghost-core',
    },
    vex: {
        plate: { lit: 'M0 -24 L-8 -18 L-8 -10 L0 -12.5 Z', shaded: 'M0 -24 L0 -12.5 L8 -10 L8 -18 Z' },
        spike: { lit: 'M-4 -19 L0 -19 L0 -10.5 L-5 -9 Z', shaded: 'M0 -19 L4 -19 L5 -9 L0 -10.5 Z' },
        lit: 'fill-buddy-ghost-vex',
        shaded: 'fill-buddy-ghost-vex-shade',
        edge: 'stroke-buddy-ghost-vex-shade',
        ring: 'fill-buddy-ghost-housing stroke-buddy-ghost-vex-shade',
        body: 'fill-buddy-ghost-housing',
        glint: 'stroke-buddy-ghost-vex-core',
        eye: 'fill-buddy-ghost-vex-eye',
        core: 'fill-buddy-ghost-vex-core',
    },
}

/** The four lesser plates' turns, on the diagonals, and the four great plates', square to the eye. */
const SPIKE_TURNS = [45, 135, 225, 315]
const PLATE_TURNS = [0, 90, 180, 270]
/** A plate's place: turned about the eye. */
const at = (turn: number) => `translate(${GHOST_CENTER.x} ${GHOST_CENTER.y}) rotate(${turn})`

/** Where the light comes from, as a unit vector from the eye: the top left. */
const LIGHT = { x: -Math.SQRT1_2, y: -Math.SQRT1_2 }
/** Which way a plate's facets face before it is turned: left and right of its ridge, and a little outwards. */
const FACING = { left: { x: -1, y: -0.35 }, right: { x: 1, y: -0.35 } }
/** How much a facet darkens at most, turned furthest from the light on its side of it. */
const MOST_DIM = { lit: 0.18, shaded: 0.32 }

/** How much darker the lesser plates are than a great plate turned the same way, standing behind them. */
const BEHIND = 0.22

/** How a facet takes the light: lit or shaded, and how much darker than its color it is. */
interface Shade {
    /** Whether it is turned to the light. */
    lit: boolean
    /** The opacity of the dark laid over it, none for a facet square to the light. */
    dim: number
}

/**
 * How each facet of a plate turned so far takes the light: left of its ridge, then right, each darkened by `behind`
 * more for a plate that stands behind others.
 */
function shadesAt(turn: number, behind = 0): { left: Shade; right: Shade } {
    const radians = (turn * Math.PI) / 180
    const [cos, sin] = [Math.cos(radians), Math.sin(radians)]
    const shade = ({ x, y }: { x: number; y: number }): Shade => {
        // How squarely the facet faces the light once turned, -1 to 1 across the facings a plate can have.
        const toward = ((x * cos - y * sin) * LIGHT.x + (x * sin + y * cos) * LIGHT.y) / Math.hypot(x, y)
        const lit = toward > 0
        return { lit, dim: (1 - Math.abs(toward)) * (lit ? MOST_DIM.lit : MOST_DIM.shaded) + (lit ? 0 : 0.1) + behind }
    }
    return { left: shade(FACING.left), right: shade(FACING.right) }
}

/**
 * A shell's plates, about the eye. With a `cue`, the great plates spread a little each time it changes, as a Ghost's do
 * when it talks; while `rave` is on, the shell turns a quarter on each beat of the lights.
 */
export function ShellPlates({ id, cue, rave = false }: { id: ShellId; cue?: number; rave?: boolean }) {
    const look = LOOKS[id]
    return (
        <g data-shell={id} className={cn(rave && 'animate-ghost-spin')}>
            {look.body === undefined ? null : (
                <circle cx={GHOST_CENTER.x} cy={GHOST_CENTER.y} r="13" className={look.body} />
            )}
            {SPIKE_TURNS.map((turn) => (
                <g key={turn} transform={at(turn)}>
                    {'leaf' in look.spike ? (
                        <path
                            d={look.spike.leaf}
                            strokeWidth="0.6"
                            strokeLinejoin="round"
                            className={cn(look.shaded, look.edge)}
                        />
                    ) : (
                        <Facets look={look} facets={look.spike} shades={shadesAt(turn, BEHIND)} />
                    )}
                </g>
            ))}
            {PLATE_TURNS.map((turn) => (
                <g key={turn} transform={at(turn)}>
                    <g key={cue} className={cn(cue !== undefined && 'animate-ghost-talk')}>
                        {'wire' in look.plate ? (
                            <path
                                d={look.plate.wire}
                                fill="none"
                                strokeWidth="1.5"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                className={look.lit}
                            />
                        ) : (
                            <Facets look={look} facets={look.plate} shades={shadesAt(turn)} />
                        )}
                    </g>
                </g>
            ))}
        </g>
    )
}

/**
 * A plate's two facets, the one left of its ridge as drawn pointing up (`lit`) and the one right of it (`shaded`), each
 * in the color the light gives it where the plate is turned (`shades`), darkened the further it faces from the light.
 */
function Facets({
    look,
    facets,
    shades,
}: {
    look: Look
    facets: { lit: string; shaded: string }
    shades: { left: Shade; right: Shade }
}) {
    const sides = [
        { d: facets.lit, shade: shades.left },
        { d: facets.shaded, shade: shades.right },
    ]
    return sides.map(({ d, shade }) => (
        <g key={d}>
            <path
                d={d}
                strokeWidth="0.6"
                strokeLinejoin="round"
                className={cn(shade.lit ? look.lit : look.shaded, look.edge)}
            />
            {shade.dim > 0.01 ? (
                <path d={d} fillOpacity={shade.dim.toFixed(2)} className="fill-buddy-ghost-housing" />
            ) : null}
        </g>
    ))
}

/**
 * The ring behind a shell's eye: for a Ghost's shell, the lens set in its body, its eye's light spilling a little onto
 * the plates around it.
 */
export function ShellRing({ id }: { id: ShellId }) {
    const look = LOOKS[id]
    return (
        <>
            {look.body === undefined ? null : (
                <circle cx={GHOST_CENTER.x} cy={GHOST_CENTER.y} r="13" fillOpacity="0.16" className={look.eye} />
            )}
            <circle cx={GHOST_CENTER.x} cy={GHOST_CENTER.y} r="9.5" strokeWidth="1.5" className={look.ring} />
        </>
    )
}

/** What a shell wears over its top plate, outside the turning shell: nothing for most. */
export function ShellCrest({ id }: { id: ShellId }) {
    return LOOKS[id].crest ?? null
}

/** The turns of a lens's blades, the iris a Ghost's eye opens and closes like a camera's. */
const BLADE_TURNS = [0, 45, 90, 135, 180, 225, 270, 315]
/** The glint on a lens's glass: an arc over the light, toward the top left, where the light falls. */
const GLINT = [
    `M${GHOST_CENTER.x - 6.6} ${GHOST_CENTER.y - 2.4}`,
    `A7 7 0 0 1 ${GHOST_CENTER.x - 2.4} ${GHOST_CENTER.y - 6.6}`,
].join(' ')

/**
 * A shell's eye, in its colors: a glow, a light, and a core for its pupil, the part that looks toward the pointer; a
 * Ghost's shell sets them behind a lens, with the blades of its iris around the light and a glint on its glass. With a
 * `cue`, it blinks now and then, its glow swells and dims, faster while `rave` is on, and it flares each time the cue
 * changes; without one it holds still.
 */
export function ShellEye({ id, cue, rave = false }: { id: ShellId; cue?: number; rave?: boolean }) {
    const look = LOOKS[id]
    const animated = cue !== undefined
    return (
        <g className={cn(animated && 'animate-buddy-blink')}>
            <g data-eye>
                <circle
                    cx={GHOST_CENTER.x}
                    cy={GHOST_CENTER.y}
                    r="7"
                    fillOpacity="0.35"
                    className={cn(look.eye, animated && (rave ? 'animate-ghost-glow-rave' : 'animate-ghost-glow'))}
                />
                {animated ? (
                    <circle
                        key={cue}
                        cx={GHOST_CENTER.x}
                        cy={GHOST_CENTER.y}
                        r="7"
                        className={cn('animate-ghost-flare', look.eye)}
                    />
                ) : null}
                <circle
                    cx={GHOST_CENTER.x}
                    cy={GHOST_CENTER.y}
                    r="4.6"
                    className={cn(animated && 'animate-ghost-light', look.eye)}
                />
                {look.body === undefined ? null : (
                    <g
                        strokeWidth="0.7"
                        strokeLinecap="round"
                        strokeOpacity="0.55"
                        className="stroke-buddy-ghost-housing"
                    >
                        {BLADE_TURNS.map((turn) => (
                            <path key={turn} d="M0 -4.9 L1.6 -6.9" transform={at(turn)} />
                        ))}
                    </g>
                )}
                <circle data-pupil cx={GHOST_CENTER.x} cy={GHOST_CENTER.y} r="2" className={look.core} />
                {look.glint === undefined ? null : (
                    <path
                        d={GLINT}
                        fill="none"
                        strokeWidth="0.9"
                        strokeLinecap="round"
                        strokeOpacity="0.7"
                        className={look.glint}
                    />
                )}
            </g>
        </g>
    )
}

/** One shell on its own, for the shop in Settings: its plates, its crest, and its eye, holding still. */
export function ShellPreview({ id, className }: { id: ShellId; className?: string }) {
    return (
        <svg viewBox="-2 -2 52 68" className={className} aria-hidden>
            <ShellPlates id={id} />
            <ShellCrest id={id} />
            <ShellRing id={id} />
            <ShellEye id={id} />
        </svg>
    )
}
