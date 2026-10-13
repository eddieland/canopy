import { describe, expect, it } from 'vitest'

import { branchUrl } from './branch-url'

describe('branchUrl', () => {
    it('puts the branch where the template says, keeping its slashes', () => {
        expect(branchUrl('https://github.com/acme/api/tree/{branch}', 'agent/ABC-102')).toBe(
            'https://github.com/acme/api/tree/agent/ABC-102',
        )
        expect(branchUrl('https://git.example/b?name={branch}', 'main')).toBe('https://git.example/b?name=main')
    })

    it('encodes each part of the name, so it cannot leave its place in the URL', () => {
        expect(branchUrl('https://h.example/tree/{branch}', 'a/b?c#d e')).toBe('https://h.example/tree/a/b%3Fc%23d%20e')
    })

    it('gives no link without a template', () => {
        expect(branchUrl(null, 'main')).toBeUndefined()
        expect(branchUrl(undefined, 'main')).toBeUndefined()
        expect(branchUrl('', 'main')).toBeUndefined()
    })
})
