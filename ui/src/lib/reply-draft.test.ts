import { afterEach, describe, expect, it } from 'vitest'

import { draftKey, dropDrafts, keepDraft, parseDraft, readDraft } from './reply-draft'

afterEach(() => {
    sessionStorage.clear()
})

describe('reply drafts', () => {
    it('keeps a draft per subject, and drops it once nothing is written', () => {
        const key = draftKey('ticket:ABC-1')
        keepDraft(key, { body: 'Use the v2 API', submission: 's-1' })
        expect(readDraft(key)).toEqual({ body: 'Use the v2 API', submission: 's-1' })
        expect(readDraft(draftKey('chore:deps'))).toBeNull()

        keepDraft(key, { body: '', submission: 's-1' })
        expect(readDraft(key)).toBeNull()
        expect(sessionStorage).toHaveLength(0)
    })

    it('drops every draft on signing out, and nothing else the tab keeps', () => {
        keepDraft(draftKey('ticket:ABC-1'), { body: 'Use the v2 API', submission: 's-1' })
        keepDraft(draftKey('chore:deps'), { body: 'Leave lodash at 4', submission: 's-2' })
        sessionStorage.setItem('other', 'kept')
        dropDrafts()
        expect(readDraft(draftKey('ticket:ABC-1'))).toBeNull()
        expect(readDraft(draftKey('chore:deps'))).toBeNull()
        expect(sessionStorage.getItem('other')).toBe('kept')
    })

    it('reads nothing that is not a draft', () => {
        expect(parseDraft(null)).toBeNull()
        expect(parseDraft('not json')).toBeNull()
        expect(parseDraft('"text"')).toBeNull()
        expect(parseDraft('{"body":"hi"}')).toBeNull()
        expect(parseDraft('{"body":"","submission":"s-1"}')).toBeNull()
        expect(parseDraft('{"body":"hi","submission":"s-1"}')).toEqual({ body: 'hi', submission: 's-1' })
    })
})
