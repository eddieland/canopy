import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderRouted } from '@/test-utils'

import { LinkedText } from './linked-text'

afterEach(() => {
    cleanup()
})

const PR = 'https://github.com/acme/web/pull/88'

describe('LinkedText', () => {
    it('links an http or https URL to itself, opening a new tab with no referrer', () => {
        render(<LinkedText text="See https://ci.example.test/run/7, then http://example.test." />)
        const links = screen.getAllByRole<HTMLAnchorElement>('link')
        expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
            ['https://ci.example.test/run/7', 'https://ci.example.test/run/7'],
            ['http://example.test', 'http://example.test'],
        ])
        for (const link of links) {
            expect(link.target).toBe('_blank')
            expect(link.rel).toBe('noreferrer noopener')
        }
    })

    it('keeps every other scheme, Markdown link, and tag as its characters', () => {
        const text =
            'javascript:alert(1) [docs](https://evil.test/x)? <a href="https://evil.test">x</a> <img src=x onerror=1>'
        const { container } = render(<LinkedText text={text} />)
        expect(container.textContent).toBe(text)
        expect(screen.queryByRole('img')).toBeNull()
        // What links is each URL as written, never a Markdown label or a tag's text.
        expect(screen.getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual([
            'https://evil.test/x',
            'https://evil.test',
        ])
    })

    it("names a GitHub PR's address as the PR, linking in to its page and out to GitHub, when asked", async () => {
        await renderRouted(<LinkedText text={`Opened ${PR}.`} pullRequests />)
        const name = screen.getByRole('link', { name: 'acme/web#88' })
        expect(name.getAttribute('href')).toBe(`/pull-requests/pr?url=${encodeURIComponent(PR)}`)
        expect(name.getAttribute('target')).toBeNull()
        const out = screen.getByRole('link', { name: 'acme/web#88 on GitHub' })
        expect(out.getAttribute('href')).toBe(PR)
        expect(out.getAttribute('target')).toBe('_blank')
        expect(out.getAttribute('rel')).toBe('noreferrer noopener')
    })

    it("leaves a PR's address as written without being asked", () => {
        render(<LinkedText text={`Opened ${PR}.`} />)
        expect(screen.getByRole('link').textContent).toBe(PR)
    })
})
