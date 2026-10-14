import { describe, expect, it } from 'vitest'

import { onGitHub, splitLinks } from './links'

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
