import { describe, expect, it } from 'vitest'

import { gitHubLabel, onGitHub, splitLinks } from './links'

describe('splitLinks', () => {
    it('leaves text without a URL whole', () => {
        expect(splitLinks('nothing to see')).toEqual([{ text: 'nothing to see' }])
        expect(splitLinks('')).toEqual([])
    })

    it('links http and https URLs and keeps the text around them', () => {
        expect(splitLinks('PR https://github.com/acme/web/pull/88 waits\nsee http://x.test/a?b=1#c')).toEqual([
            { text: 'PR ' },
            { text: 'https://github.com/acme/web/pull/88', href: 'https://github.com/acme/web/pull/88' },
            { text: ' waits\nsee ' },
            { text: 'http://x.test/a?b=1#c', href: 'http://x.test/a?b=1#c' },
        ])
    })

    it('leaves sentence punctuation and an unopened bracket outside the link', () => {
        expect(splitLinks('(see https://x.test/a).')).toEqual([
            { text: '(see ' },
            { text: 'https://x.test/a', href: 'https://x.test/a' },
            { text: ').' },
        ])
        expect(splitLinks('https://en.wikipedia.org/wiki/Tree_(graph), then')[0]).toEqual({
            text: 'https://en.wikipedia.org/wiki/Tree_(graph)',
            href: 'https://en.wikipedia.org/wiki/Tree_(graph)',
        })
    })

    it('links no other scheme, and nothing without a host', () => {
        for (const text of ['javascript:alert(1)', 'file:///etc/passwd', 'mailto:a@b.test', 'https://', 'https://.']) {
            expect(splitLinks(text)).toEqual([{ text }])
        }
        expect(splitLinks('xhttps://x.test')).toEqual([{ text: 'xhttps://x.test' }])
    })

    it('stops a URL at a quote or an angle bracket', () => {
        expect(splitLinks('<https://x.test/a>"')).toEqual([
            { text: '<' },
            { text: 'https://x.test/a', href: 'https://x.test/a' },
            { text: '>"' },
        ])
    })
})

describe('onGitHub', () => {
    it('is true for a github.com URL alone', () => {
        expect(onGitHub('https://github.com/acme/web/pull/88')).toBe(true)
        expect(onGitHub('https://gitlab.com/acme/web/-/merge_requests/3')).toBe(false)
        expect(onGitHub('https://github.com.evil.test/acme/web')).toBe(false)
        expect(onGitHub('https://acme.atlassian.net/browse/ABC-1')).toBe(false)
        expect(onGitHub('not a url')).toBe(false)
    })
})

describe('gitHubLabel', () => {
    it('names a PR, an issue, and a commit as GitHub writes a reference', () => {
        expect(gitHubLabel('https://github.com/acme/web/pull/88')).toBe('acme/web#88')
        expect(gitHubLabel('https://github.com/acme/web/pull/88/')).toBe('acme/web#88')
        expect(gitHubLabel('https://github.com/acme/web/issues/7')).toBe('acme/web#7')
        expect(gitHubLabel('https://github.com/acme/web/commit/1a2b3c4d5e6f')).toBe('acme/web@1a2b3c4')
    })

    it('names an advisory by its id', () => {
        expect(gitHubLabel('https://github.com/advisories/GHSA-35jh-r3h4-6jhm')).toBe('GHSA-35jh-r3h4-6jhm')
    })

    it('names anything else by its address after github.com', () => {
        expect(gitHubLabel('https://github.com/acme/web')).toBe('acme/web')
        expect(gitHubLabel('https://github.com/acme/web/pull/88/files')).toBe('acme/web/pull/88/files')
        expect(gitHubLabel('https://github.com/acme/web/pull/88#issuecomment-1')).toBe(
            'acme/web/pull/88#issuecomment-1',
        )
        expect(gitHubLabel('https://github.com/acme/web/pull/eight')).toBe('acme/web/pull/eight')
        expect(gitHubLabel('https://github.com/acme/web/blob/main/a.ts')).toBe('acme/web/blob/main/a.ts')
        expect(gitHubLabel('https://github.com/')).toBe('github.com')
        expect(gitHubLabel('https://github.com')).toBe('github.com')
    })
})
