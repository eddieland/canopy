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
        const draft = { url: PR, notes: 'Mind the migration', picked: ['skeptic'], model: 'acme/deep-2@high' }
        keepReviewRequestDraft(draft)
        expect(readReviewRequestDraft()).toEqual(draft)
        dropReviewRequestDraft()
        expect(readReviewRequestDraft()).toEqual(EMPTY_DRAFT)

        keepReviewRequestDraft({ url: PR, notes: '', picked: null, model: null })
        keepReviewRequestDraft(EMPTY_DRAFT)
        expect(sessionStorage).toHaveLength(0)
    })

    it('keeps a model picked alone, and clearing it back to the default keeps nothing', () => {
        keepReviewRequestDraft({ ...EMPTY_DRAFT, model: 'acme/deep-2' })
        expect(readReviewRequestDraft()).toEqual({ ...EMPTY_DRAFT, model: 'acme/deep-2' })
        keepReviewRequestDraft({ ...EMPTY_DRAFT, model: null })
        expect(sessionStorage).toHaveLength(0)
    })

    it('reads nothing that is not a draft', () => {
        expect(parseReviewRequestDraft(null)).toBeNull()
        expect(parseReviewRequestDraft('not json')).toBeNull()
        expect(parseReviewRequestDraft('[]')).toBeNull()
        expect(parseReviewRequestDraft(JSON.stringify({ url: PR }))).toBeNull()
        expect(parseReviewRequestDraft(JSON.stringify({ url: PR, notes: '', picked: [1] }))).toBeNull()
        expect(parseReviewRequestDraft(JSON.stringify({ url: PR, notes: '', picked: null, model: 2 }))).toBeNull()
        // One kept before drafts held a model has none.
        expect(parseReviewRequestDraft(JSON.stringify({ url: PR, notes: '', picked: null }))).toEqual({
            url: PR,
            notes: '',
            picked: null,
            model: null,
        })
    })
})
