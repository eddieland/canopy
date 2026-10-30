import { describe, expect, it } from 'vitest'

import { pickWindow, windowId, windowName } from './report-window'

describe('report windows', () => {
    it('names a window and gives it an id, in hours or in days', () => {
        expect([windowName({ hours: 24 }), windowName({ days: 7 }), windowName({ days: 1 })]).toEqual([
            '24 hours',
            '7 days',
            '1 day',
        ])
        expect([windowId({ hours: 24 }), windowId({ days: 30 })]).toEqual(['24h', '30'])
    })

    it('takes only the windows offered, hours before days', () => {
        const offered = [{ hours: 24 }, { days: 7 }, { days: 30 }] as const
        expect(pickWindow(offered, { days: '30' })).toEqual({ days: 30 })
        expect(pickWindow(offered, { hours: 24, days: 30 })).toEqual({ hours: 24 })
        expect(pickWindow([{ days: 7 }, { days: 30 }], { hours: 24 })).toBeUndefined()
        expect(pickWindow(offered, { days: '8' })).toBeUndefined()
        expect(pickWindow(offered, {})).toBeUndefined()
    })
})
