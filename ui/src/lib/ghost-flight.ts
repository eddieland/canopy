/**
 * Where the Ghost flies next, at the foot of the rail (`GhostFigure` in src/components/shell/buddy.tsx). It never
 * follows a loop: each leg flies to a spot picked at random in the sky it has, slowly or, now and then, in a dart, and
 * rests there a while picked at random too, bobbing on its own beat, before the next. It leans into each leg. The sky
 * is how far right of its rest it may go and how far up: high while the rail has room and no tip is up, low otherwise,
 * so it never covers the bubble or the blocks above it.
 */

/** A spot in the Ghost's sky, in its drawing's units from where it rests: right is positive, up is negative. */
export interface Spot {
    /** How far right of its rest. */
    x: number
    /** How far below its rest: negative, as it rises. */
    y: number
}

/** How far the Ghost may fly from where it rests. */
export interface Sky {
    /** How far right, never past the width of the bubble above it. */
    right: number
    /** How far up. */
    rise: number
}

/** One leg of the Ghost's flight. */
export interface Leg {
    /** Where it flies to. */
    to: Spot
    /** How long the flight takes, in milliseconds. */
    ms: number
    /** How far it leans into the leg at its fastest, in degrees: right for a leg to the right. */
    lean: number
    /** How long it rests there before the next leg, in milliseconds. */
    rest: number
    /** Whether it darts there, quick and sharp, rather than drifting. */
    dart: boolean
}

/** The sky while the rail has room for the Ghost and its bubble, and no tip is up. */
export const HIGH_SKY: Sky = { right: 38, rise: 30 }
/** The sky while a tip is up, or the rail is short: it keeps near the floor. */
export const LOW_SKY: Sky = { right: 38, rise: 6 }

/** How often a leg is a dart. */
const DART_CHANCE = 0.15
/** The shortest leg worth flying, in drawing units: a shorter pick is picked again, a few times at most. */
const LEAST_HOP = 8
/** The shortest and longest rest between legs, in milliseconds; a dart's is always the shortest. */
const REST_MS = { least: 400, most: 3200 }
/** How far it leans at most, in degrees, and how much per unit it flies sideways, drifting and darting. */
const LEAN = { most: 10, drift: 0.3, dart: 0.5 }

/** The next leg from `from`, in `sky`: a spot in it picked at random, and how the Ghost gets there. */
export function nextLeg(from: Spot, sky: Sky, random: () => number = Math.random): Leg {
    let to = pick(sky, random)
    for (let tries = 1; tries < 4 && Math.hypot(to.x - from.x, to.y - from.y) < LEAST_HOP; tries += 1) {
        to = pick(sky, random)
    }
    const dart = random() < DART_CHANCE
    const far = Math.hypot(to.x - from.x, to.y - from.y)
    const ms = dart ? 380 + far * 9 : 1200 + far * 40 + random() * 1400
    const lean = (to.x - from.x) * (dart ? LEAN.dart : LEAN.drift)
    const rest = dart ? REST_MS.least : REST_MS.least + random() * (REST_MS.most - REST_MS.least)
    return {
        to,
        ms: Math.round(ms),
        lean: Math.max(-LEAN.most, Math.min(LEAN.most, lean)),
        rest: Math.round(rest),
        dart,
    }
}

/** Whether `spot` is in `sky`: a Ghost outside it, flying high when its sky came down, flies back in at once. */
export function inSky(spot: Spot, sky: Sky): boolean {
    return spot.x >= 0 && spot.x <= sky.right && spot.y <= 0 && spot.y >= -sky.rise
}

/** A spot in `sky` picked at random, more often low than high: a Ghost keeps near its floor, rising now and then. */
function pick(sky: Sky, random: () => number): Spot {
    const x = random() * sky.right
    const y = -(random() ** 1.6) * sky.rise
    return { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 }
}
