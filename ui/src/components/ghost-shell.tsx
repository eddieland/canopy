import type { ShellId } from '@/lib/shells'
import { cn } from '@/lib/utils'

/**
 * The Ghost's shells (src/lib/shells.ts), drawn in the Ghost's own units (`GhostFigure` in
 * src/components/shell/buddy.tsx): four great plates around its eye, four lesser ones behind them on the diagonals,
 * and, for some, a crest on top. Each shell is a look: the plates' shape and colors, the ring behind the eye, and the
 * eye's glow and core. `ShellPreview` shows one on its own, for the shop.
 */

/** Where the Ghost's eye sits in its drawing, which its shell turns about. */
const GHOST_CENTER = { x: 24, y: 40 }

/** How a shell looks: its plates' shapes, each part's color class, and what it wears on top. */
interface Look {
    /** One great plate, pointing up from the eye: its lit facet left of the ridge and its shaded one right. */
    plate: { lit: string; shaded: string }
    /** One lesser plate, behind the great ones on the diagonals, all in shade. */
    spike: string
    /** The fill of a plate's lit facet. */
    lit: string
    /** The fill of a plate's shaded facet, and of the lesser plates. */
    shaded: string
    /** The outline every plate gets, to stand off a light canvas. */
    edge: string
    /** The ring behind the eye. */
    ring: string
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
    spike: 'M0 -20 L-5 -9 L5 -9 Z',
}

/** Each shell's look. */
const LOOKS: Record<ShellId, Look> = {
    generalist: {
        ...FACETED,
        lit: 'fill-buddy-ghost-shell',
        shaded: 'fill-buddy-ghost-facet',
        edge: 'stroke-buddy-ghost-facet',
        ring: 'fill-buddy-ghost-facet',
        eye: 'fill-buddy-ghost-eye',
        core: 'fill-buddy-ghost-core',
    },
    // Sprig, as a Ghost: leaves for plates, its paperclip's wire for the ring, one googly eye, and its sprig on top.
    sprig: {
        plate: { lit: 'M0 -25 C-7 -21 -8 -14 0 -11 Z', shaded: 'M0 -25 L0 -11 C8 -14 7 -21 0 -25 Z' },
        spike: 'M0 -20 C-4 -17 -4 -11 0 -9 C4 -11 4 -17 0 -20 Z',
        lit: 'fill-buddy-leaf',
        shaded: 'fill-buddy-leaf-shade',
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
        spike: 'M0 -19 Q-6 -15 -5 -9 L5 -9 Q6 -15 0 -19 Z',
        lit: 'fill-buddy-ghost-pumpkin',
        shaded: 'fill-buddy-ghost-pumpkin-shade',
        edge: 'stroke-buddy-ghost-pumpkin-shade',
        ring: 'fill-buddy-ghost-pumpkin-shade',
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
        ring: 'fill-buddy-ghost-facet',
        eye: 'fill-buddy-ghost-eye',
        core: 'fill-buddy-ghost-core',
    },
    vex: {
        plate: { lit: 'M0 -24 L-8 -18 L-8 -10 L0 -12.5 Z', shaded: 'M0 -24 L0 -12.5 L8 -10 L8 -18 Z' },
        spike: 'M-4 -19 L4 -19 L5 -9 L-5 -9 Z',
        lit: 'fill-buddy-ghost-vex',
        shaded: 'fill-buddy-ghost-vex-shade',
        edge: 'stroke-buddy-ghost-vex-shade',
        ring: 'fill-buddy-ghost-vex-shade',
        eye: 'fill-buddy-ghost-vex-eye',
        core: 'fill-buddy-ghost-vex-core',
    },
}

/** The four lesser plates' turns, on the diagonals, and the four great plates', square to the eye. */
const SPIKE_TURNS = [45, 135, 225, 315]
const PLATE_TURNS = [0, 90, 180, 270]
/** A plate's place: turned about the eye. */
const at = (turn: number) => `translate(${GHOST_CENTER.x} ${GHOST_CENTER.y}) rotate(${turn})`

/**
 * A shell's plates, about the eye. With a `cue`, the great plates spread a little each time it changes, as a Ghost's do
 * when it talks; while `rave` is on, the shell turns a quarter on each beat of the lights.
 */
export function ShellPlates({ id, cue, rave = false }: { id: ShellId; cue?: number; rave?: boolean }) {
    const look = LOOKS[id]
    return (
        <g data-shell={id} className={cn(rave && 'animate-ghost-spin')}>
            {SPIKE_TURNS.map((turn) => (
                <path
                    key={turn}
                    d={look.spike}
                    transform={at(turn)}
                    strokeWidth="0.6"
                    strokeLinejoin="round"
                    className={cn(look.shaded, look.edge)}
                />
            ))}
            {PLATE_TURNS.map((turn) => (
                <g key={turn} transform={at(turn)}>
                    <g key={cue} className={cn(cue !== undefined && 'animate-ghost-talk')}>
                        <path
                            d={look.plate.lit}
                            strokeWidth="0.6"
                            strokeLinejoin="round"
                            className={cn(look.lit, look.edge)}
                        />
                        <path
                            d={look.plate.shaded}
                            strokeWidth="0.6"
                            strokeLinejoin="round"
                            className={cn(look.shaded, look.edge)}
                        />
                    </g>
                </g>
            ))}
        </g>
    )
}

/** The ring behind a shell's eye. */
export function ShellRing({ id }: { id: ShellId }) {
    return <circle cx={GHOST_CENTER.x} cy={GHOST_CENTER.y} r="9.5" strokeWidth="1.5" className={LOOKS[id].ring} />
}

/** What a shell wears over its top plate, outside the turning shell: nothing for most. */
export function ShellCrest({ id }: { id: ShellId }) {
    return LOOKS[id].crest ?? null
}

/**
 * A shell's eye, in its colors: a glow, a light, and a core for its pupil, the part that looks toward the pointer. With
 * a `cue`, it blinks now and then, its glow swells and dims, faster while `rave` is on, and it flares each time the cue
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
                <circle data-pupil cx={GHOST_CENTER.x} cy={GHOST_CENTER.y} r="2" className={look.core} />
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
