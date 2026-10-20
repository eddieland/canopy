import { describe, expect, it } from 'vitest'

import { mockReviews } from '@/api/mocks'
import type { PullRequest, ReviewSummary } from '@/api/types'

import {
    countText,
    filterWords,
    PR_QUERY_MAX,
    prQueryOf,
    prRepoOf,
    pullRequestShown,
    reposOf,
    requestShown,
    reviewShown,
} from './pull-request-filter'

const pr: Pick<PullRequest, 'url' | 'repo' | 'ticket_key' | 'ticket_title' | 'title'> = {
    url: 'https://github.com/acme/web/pull/88',
    repo: 'web',
    ticket_key: 'ABC-099',
    ticket_title: 'Debounce search input',
    title: 'ABC-099: debounce the search box by 250 ms',
}
const review = mockReviews[0] as ReviewSummary

describe('prQueryOf', () => {
    it('keeps text with a word in it, cut to the longest it keeps', () => {
        expect(prQueryOf('web#88')).toBe('web#88')
        expect(prQueryOf('x'.repeat(PR_QUERY_MAX + 5))).toHaveLength(PR_QUERY_MAX)
    })

    it('drops blank text and anything not a string', () => {
        expect(prQueryOf('  ')).toBeUndefined()
        expect(prQueryOf(88)).toBeUndefined()
        expect(prQueryOf(undefined)).toBeUndefined()
    })
})

describe('prRepoOf', () => {
    it('keeps a repository name and drops anything else', () => {
        expect(prRepoOf('web')).toBe('web')
        expect(prRepoOf('web-2')).toBe('web-2')
        expect(prRepoOf('Web')).toBeUndefined()
        expect(prRepoOf('../web')).toBeUndefined()
        expect(prRepoOf(['web'])).toBeUndefined()
    })
})

describe('reposOf', () => {
    it('names each repository a row is in once, sorted, and the one chosen', () => {
        expect(reposOf([{ repo: 'web' }, { repo: null }, { repo: 'api' }, { repo: 'web' }], undefined)).toEqual([
            'api',
            'web',
        ])
        expect(reposOf([{ repo: 'web' }], 'mobile')).toEqual(['mobile', 'web'])
    })
})

describe('pullRequestShown', () => {
    it('shows every PR with no filter', () => {
        expect(pullRequestShown(pr, {})).toBe(true)
    })

    it('keeps a PR in the chosen repository and leaves out one in another, or in none', () => {
        expect(pullRequestShown(pr, { repo: 'web' })).toBe(true)
        expect(pullRequestShown(pr, { repo: 'api' })).toBe(false)
        expect(pullRequestShown({ ...pr, repo: null }, { repo: 'web' })).toBe(false)
    })

    it('finds every word, in any case, in its name, ticket, or titles', () => {
        expect(pullRequestShown(pr, { q: 'web#88' })).toBe(true)
        expect(pullRequestShown(pr, { q: 'abc-099 DEBOUNCE' })).toBe(true)
        expect(pullRequestShown(pr, { q: '250 ms' })).toBe(true)
        expect(pullRequestShown({ ...pr, title: null }, { q: 'input' })).toBe(true)
        expect(pullRequestShown(pr, { q: 'debounce billing' })).toBe(false)
    })

    it('holds both filters at once', () => {
        expect(pullRequestShown(pr, { repo: 'web', q: 'search' })).toBe(true)
        expect(pullRequestShown(pr, { repo: 'api', q: 'search' })).toBe(false)
    })
})

describe('reviewShown', () => {
    it('finds a review by its PR, ticket, or commit, in its repository', () => {
        expect(reviewShown(review, { q: 'web#91' })).toBe(true)
        expect(reviewShown(review, { q: 'abc-103' })).toBe(true)
        expect(reviewShown(review, { q: '9b1d4e' })).toBe(true)
        expect(reviewShown(review, { repo: 'web', q: 'acme/web' })).toBe(true)
        expect(reviewShown(review, { repo: 'api' })).toBe(false)
        expect(reviewShown(review, { q: 'abc-104' })).toBe(false)
    })
})

describe('requestShown', () => {
    const request = { pr_url: 'https://github.com/acme/api/pull/12' }

    it('finds a waiting PR by its name', () => {
        expect(requestShown(request, {})).toBe(true)
        expect(requestShown(request, { q: 'api#12' })).toBe(true)
        expect(requestShown(request, { q: 'web' })).toBe(false)
    })

    it('leaves it out under any repository, which no tick has read yet', () => {
        expect(requestShown(request, { repo: 'api' })).toBe(false)
    })
})

describe('filterWords', () => {
    it('says which filters left nothing', () => {
        expect(filterWords({})).toBe('')
        expect(filterWords({ repo: 'api' })).toBe(' in api')
        expect(filterWords({ repo: 'api', q: ' retry ' })).toBe(' in api with “retry”')
    })
})

describe('countText', () => {
    it('counts the rows, and of how many once a filter left some out', () => {
        expect(countText(undefined, 12, false)).toBe('')
        expect(countText(12, 12, false)).toBe('12')
        expect(countText(3, 12, true)).toBe('3 of 12')
    })
})
