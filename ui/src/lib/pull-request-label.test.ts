import { describe, expect, it } from 'vitest'

import { pullRequestLabel } from './pull-request-label'

describe('pullRequestLabel', () => {
    it('names a GitHub PR as GitHub writes a reference', () => {
        expect(pullRequestLabel('https://github.com/acme/web/pull/88')).toBe('acme/web#88')
        expect(pullRequestLabel('https://github.com/acme/web/pull/88/')).toBe('acme/web#88')
    })

    it('keeps any other address as written, without https://', () => {
        expect(pullRequestLabel('https://git.example/acme/web/pull/88')).toBe('git.example/acme/web/pull/88')
        expect(pullRequestLabel('https://github.com/acme/web/pull/88/files')).toBe('github.com/acme/web/pull/88/files')
        expect(pullRequestLabel('https://github.com/acme/web/issues/88')).toBe('github.com/acme/web/issues/88')
        expect(pullRequestLabel('https://github.com/acme/web/pull/88?x=1')).toBe('github.com/acme/web/pull/88?x=1')
    })
})
