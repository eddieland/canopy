import { describe, expect, it } from 'vitest'

import { ticketUrl } from './ticket-url'

describe('ticketUrl', () => {
    it('puts the key where the template says', () => {
        expect(ticketUrl('https://jira.example/browse/{key}', 'ABC-102')).toBe('https://jira.example/browse/ABC-102')
        expect(ticketUrl('https://t.example/i?id={key}&x=1', 'ABC-1')).toBe('https://t.example/i?id=ABC-1&x=1')
    })

    it('encodes the key, so it cannot leave its place in the URL', () => {
        expect(ticketUrl('https://t.example/{key}', 'a/../b?c#d')).toBe('https://t.example/a%2F..%2Fb%3Fc%23d')
    })

    it('gives no link without a template', () => {
        expect(ticketUrl(null, 'ABC-102')).toBeUndefined()
        expect(ticketUrl(undefined, 'ABC-102')).toBeUndefined()
        expect(ticketUrl('', 'ABC-102')).toBeUndefined()
    })
})
