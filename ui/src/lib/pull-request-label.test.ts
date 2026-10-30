import { describe, expect, it } from 'vitest'

import { isPullRequest, pullRequestLabel, pullRequestReference, pullRequestUrl } from './pull-request-label'

// Links into a PR that GitHub writes: a tab, a thread, a review, a comment, a query.
const INTO = [
    'https://github.com/acme/web/pull/88/files',
    'https://github.com/acme/web/pull/88/files#r123',
    'https://github.com/acme/web/pull/88#discussion_r123',
    'https://github.com/acme/web/pull/88#pullrequestreview-456',
    'https://github.com/acme/web/pull/88/commits/abc123',
    'https://github.com/acme/web/pull/88?notification_referrer_id=x',
]

// Addresses that are not a GitHub PR's.
const NOT = [
    'https://git.example/acme/web/pull/88',
    'https://github.com/acme/web/issues/88',
    'https://github.com/acme/web/pull/88abc',
    'https://github.com/acme/web/pull/',
    'http://github.com/acme/web/pull/88',
]

describe('pullRequestLabel', () => {
    it('names a GitHub PR as GitHub writes a reference', () => {
        expect(pullRequestLabel('https://github.com/acme/web/pull/88')).toBe('acme/web#88')
        expect(pullRequestLabel('https://github.com/acme/web/pull/88/')).toBe('acme/web#88')
    })

    it('names a link into a GitHub PR, such as a thread, as the PR', () => {
        for (const url of INTO) {
            expect(pullRequestLabel(url)).toBe('acme/web#88')
        }
    })

    it('keeps any other address as written, without https://', () => {
        expect(pullRequestLabel('https://git.example/acme/web/pull/88')).toBe('git.example/acme/web/pull/88')
        expect(pullRequestLabel('https://github.com/acme/web/issues/88')).toBe('github.com/acme/web/issues/88')
        expect(pullRequestLabel('https://github.com/acme/web/pull/88abc')).toBe('github.com/acme/web/pull/88abc')
    })
})

describe('isPullRequest', () => {
    it("is a GitHub PR's address or a link into one, and nothing else", () => {
        expect(isPullRequest('https://github.com/acme/web/pull/88')).toBe(true)
        expect(INTO.filter((url) => !isPullRequest(url))).toEqual([])
        expect(NOT.filter((url) => isPullRequest(url))).toEqual([])
    })
})

describe('pullRequestUrl', () => {
    it("is the PR's own address, from it or any link into it, and null for any other", () => {
        const pr = 'https://github.com/acme/web/pull/88'
        expect(pullRequestUrl(pr)).toBe(pr)
        expect(pullRequestUrl(`${pr}/`)).toBe(pr)
        for (const url of INTO) {
            expect(pullRequestUrl(url)).toBe(pr)
        }
        for (const url of NOT) {
            expect(pullRequestUrl(url)).toBeNull()
        }
    })
})

describe('pullRequestReference', () => {
    it("names a GitHub PR, or a link into one, by its reference, and another host's PR by its address", () => {
        for (const url of ['https://github.com/acme/web/pull/88', ...INTO]) {
            expect(pullRequestReference(url)).toBe('acme/web#88')
        }
        expect(pullRequestReference('https://git.example/acme/web/pull/88')).toBe('git.example/acme/web/pull/88')
    })

    it('is null for anything canopy would not take as a PR', () => {
        // Every address above that is not a GitHub PR's but the other host's PR, which canopy takes.
        for (const url of NOT.slice(1)) {
            expect(pullRequestReference(url)).toBeNull()
        }
        expect(pullRequestReference('ABC-102')).toBeNull()
        expect(pullRequestReference('acme/web#88')).toBeNull()
        expect(pullRequestReference('https://git.example/acme/web/pull/88/files')).toBeNull()
    })
})
