import { describe, expect, it } from 'vitest'

import { inRepos, repoListFrom, repoListOf, reposIn, reposSummary, reposWords } from './repo-filter'

describe('repoListOf', () => {
    it('keeps one repository name, as the pages kept before they took several', () => {
        expect(repoListOf('web')).toBe('web')
        expect(repoListOf('web-2')).toBe('web-2')
    })

    it('keeps several, once each and sorted', () => {
        expect(repoListOf('web,api,web')).toBe('api,web')
    })

    it('drops what no repository could be named, and is undefined when nothing is left', () => {
        expect(repoListOf('Web,api,../etc')).toBe('api')
        expect(repoListOf('Web')).toBeUndefined()
        expect(repoListOf(',')).toBeUndefined()
        expect(repoListOf('')).toBeUndefined()
        expect(repoListOf(['web'])).toBeUndefined()
        expect(repoListOf(3)).toBeUndefined()
    })
})

describe('repoListFrom and reposIn', () => {
    it('round-trip the names chosen, and none is no filter', () => {
        expect(repoListFrom(['web', 'api'])).toBe('api,web')
        expect(repoListFrom([])).toBeUndefined()
        expect(reposIn('api,web')).toEqual(['api', 'web'])
        expect(reposIn(undefined)).toEqual([])
    })
})

describe('inRepos', () => {
    it('shows every row with nothing chosen, else a row in one of those chosen', () => {
        expect(inRepos('web', undefined)).toBe(true)
        expect(inRepos(null, undefined)).toBe(true)
        expect(inRepos('web', 'api,web')).toBe(true)
        expect(inRepos('mobile', 'api,web')).toBe(false)
        expect(inRepos(null, 'api')).toBe(false)
    })

    it('matches a whole name, not part of one', () => {
        expect(inRepos('web', 'web-2')).toBe(false)
    })
})

describe('reposWords', () => {
    it('says one, two, or more repositories as a sentence does', () => {
        expect(reposWords('api')).toBe('api')
        expect(reposWords('api,web')).toBe('api or web')
        expect(reposWords('api,web,worker')).toBe('api, web, or worker')
    })
})

describe('reposSummary', () => {
    it('names what is chosen while it fits, then counts it', () => {
        expect(reposSummary([])).toBe('every repository')
        expect(reposSummary(['api'])).toBe('api')
        expect(reposSummary(['api', 'web'])).toBe('api, web')
        expect(reposSummary(['api', 'web', 'worker'])).toBe('3 repositories')
    })
})
