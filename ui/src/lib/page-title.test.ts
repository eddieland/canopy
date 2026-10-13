import { describe, expect, it } from 'vitest'

import { pageTitle } from './page-title'

describe('pageTitle', () => {
    it('leads with the attention count, then the page, then canopy', () => {
        expect(pageTitle('PROJ-12 Fix the login', 3)).toBe('(3) PROJ-12 Fix the login · canopy')
    })

    it('leaves the count out while the attention list is empty or not read yet', () => {
        expect(pageTitle('Runs', 0)).toBe('Runs · canopy')
        expect(pageTitle('Runs', undefined)).toBe('Runs · canopy')
    })

    it('is just canopy for a page with no name', () => {
        expect(pageTitle(undefined, 2)).toBe('(2) canopy')
        expect(pageTitle('', undefined)).toBe('canopy')
    })
})
