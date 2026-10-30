import { beforeEach, describe, expect, it } from 'vitest'

import {
    dropReviewRequestDraft,
    EMPTY_DRAFT,
    keepReviewRequestDraft,
    parseReviewRequestDraft,
    readReviewRequestDraft,
} from './review-request-draft'

const PR = 'https://github.com/acme/web/pull/88'

beforeEach(() => {
    sessionStorage.clear()
})

describe('the review request draft', () => {
    it('is kept in this tab until dropped, and an empty one is not kept at all', () => {
        expect(readReviewRequestDraft()).toEqual(EMPTY_DRAFT)
        keepReviewRequestDraft({ url: PR, notes: 'Mind the migration', picked: ['skeptic'] })
        expect(readReviewRequestDraft()).toEqual({ url: PR, notes: 'Mind the migration', picked: ['skeptic'] })
        dropReviewRequestDraft()
        expect(readReviewRequestDraft()).toEqual(EMPTY_DRAFT)

        keepReviewRequestDraft({ url: PR, notes: '', picked: null })
        keepReviewRequestDraft(EMPTY_DRAFT)
        expect(sessionStorage).toHaveLength(0)
    })

    it('reads nothing that is not a draft', () => {
        expect(parseReviewRequestDraft(null)).toBeNull()
        expect(parseReviewRequestDraft('not json')).toBeNull()
        expect(parseReviewRequestDraft('[]')).toBeNull()
        expect(parseReviewRequestDraft(JSON.stringify({ url: PR }))).toBeNull()
        expect(parseReviewRequestDraft(JSON.stringify({ url: PR, notes: '', picked: [1] }))).toBeNull()
        expect(parseReviewRequestDraft(JSON.stringify({ url: PR, notes: '', picked: null }))).toEqual({
            url: PR,
            notes: '',
            picked: null,
        })
    })
})
