import { describe, expect, it } from 'vitest'

import { hoursChange, pointsChange, readoutDelta, usdChange, wholeChange } from './readout-delta'

const whole = (n: number) => String(Math.round(n))
const usd = (n: number) => `$${n.toFixed(2)}`

describe('readoutDelta', () => {
    it('says the change with its sign, in its unit', () => {
        expect(readoutDelta(5, 2, whole)).toEqual({ text: '+3', direction: 'up', worse: false })
        expect(readoutDelta(1.3, 2.5, usd)).toEqual({ text: '−$1.20', direction: 'down', worse: false })
    })

    it('says same when the figure, as its unit writes it, did not move', () => {
        expect(readoutDelta(4, 4, whole)).toEqual({ text: 'same', direction: 'same', worse: false })
        expect(readoutDelta(1.001, 1, usd)).toEqual({ text: 'same', direction: 'same', worse: false })
    })

    it('marks a move against the better way as worse, and nothing worse where the page says no way is better', () => {
        expect(readoutDelta(0.4, 0.2, whole, 'down')?.worse).toBe(false)
        expect(readoutDelta(4, 2, whole, 'down')?.worse).toBe(true)
        expect(readoutDelta(2, 4, whole, 'down')?.worse).toBe(false)
        expect(readoutDelta(2, 4, whole, 'up')?.worse).toBe(true)
        expect(readoutDelta(40, 2, usd)?.worse).toBe(false)
    })

    it('is nothing without both figures', () => {
        expect(readoutDelta(3, null, whole)).toBeNull()
        expect(readoutDelta(undefined, 3, whole)).toBeNull()
    })
})

describe('the changes a tile says', () => {
    it('writes a count whole, a share in points, a cost as costs are, and a span as the reports write one', () => {
        expect(readoutDelta(4, 5, wholeChange)?.text).toBe('−1')
        expect(readoutDelta(0.75, 0.6, pointsChange)?.text).toBe('+15 pts')
        expect(readoutDelta(0.5, 0.501, pointsChange)?.text).toBe('same')
        expect(readoutDelta(1234.5, 0.5, usdChange)?.text).toBe('+$1,234.00')
        expect(readoutDelta(3, 1.5, hoursChange, 'down')).toEqual({ text: '+1.5h', direction: 'up', worse: true })
    })
})
