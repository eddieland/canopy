import { describe, expect, it } from 'vitest'

import { goneText, removedAfter } from './retention'

describe('removedAfter', () => {
    it('says after how many days, one day by its singular', () => {
        expect(removedAfter(30)).toBe('removed after 30 days')
        expect(removedAfter(1)).toBe('removed after 1 day')
    })
})

describe('goneText', () => {
    it('names retention for a file it removed, and says the page’s own words for one gone otherwise', () => {
        expect(goneText(7, 'its log is gone')).toBe('removed after 7 days, as your [retention] keeps it')
        expect(goneText(null, 'its log is gone')).toBe('its log is gone')
    })
})
