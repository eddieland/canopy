import { describe, expect, it } from 'vitest'

import { HIGH_SKY, LOW_SKY, inSky, nextLeg } from '@/lib/ghost-flight'

/** A random source that plays `values` in turn, then the last of them forever. */
function playing(...values: number[]): () => number {
    let n = 0
    return () => values[Math.min(n++, values.length - 1)] ?? 0
}

describe('nextLeg', () => {
    it('always flies somewhere in its sky', () => {
        let at = { x: 0, y: 0 }
        for (let n = 0; n < 500; n += 1) {
            const leg = nextLeg(at, HIGH_SKY)
            expect(inSky(leg.to, HIGH_SKY)).toBe(true)
            at = leg.to
        }
    })

    it('flies back into a sky that came down', () => {
        const leg = nextLeg({ x: 20, y: -28 }, LOW_SKY)
        expect(inSky(leg.to, LOW_SKY)).toBe(true)
    })

    it('picks again a spot too close to where it is', () => {
        // The first pick is where it rests; the second, at the far top right, is far enough.
        const leg = nextLeg({ x: 0, y: 0 }, HIGH_SKY, playing(0, 0, 1, 1, 0.5))
        expect(leg.to).toEqual({ x: HIGH_SKY.right, y: -HIGH_SKY.rise })
    })

    it('leans into the way it goes, never past its most', () => {
        expect(nextLeg({ x: 0, y: 0 }, HIGH_SKY, playing(1, 0, 0.5)).lean).toBeGreaterThan(0)
        expect(nextLeg({ x: 38, y: 0 }, HIGH_SKY, playing(0, 0, 0.5)).lean).toBeLessThan(0)
        expect(Math.abs(nextLeg({ x: 0, y: 0 }, HIGH_SKY, playing(1, 0, 0)).lean)).toBeLessThanOrEqual(10)
    })

    it('darts now and then, quicker than it drifts, and rests least after one', () => {
        const dart = nextLeg({ x: 0, y: 0 }, HIGH_SKY, playing(1, 0, 0))
        const drift = nextLeg({ x: 0, y: 0 }, HIGH_SKY, playing(1, 0, 0.9))
        expect(dart.dart).toBe(true)
        expect(drift.dart).toBe(false)
        expect(dart.ms).toBeLessThan(drift.ms)
        expect(dart.rest).toBeLessThanOrEqual(drift.rest)
    })
})
