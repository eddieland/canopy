import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { GuidePiece } from '@/lib/guide'
import type { Block } from '@/lib/rich-text'
import { renderRouted } from '@/test-utils'

import { GuideLines, GuideText } from './guide-text'

// A code block's colors, which Shiki stops giving a line it has read for too long: a busy runner's (`untimedShiki`).
vi.mock('shiki/core', async (importOriginal) => (await import('@/test-utils')).untimedShiki(await importOriginal()))

afterEach(() => {
    cleanup()
})

const text = (words: string): GuidePiece => ({ kind: 'text', text: words })

describe('GuideText', () => {
    it("gives each heading its anchor as its id and a link to itself, a section's at h2 and below at h3", async () => {
        const blocks: Block<GuidePiece>[] = [
            { kind: 'heading', level: 2, line: [text('The rail, '), { kind: 'code', text: 'at a glance' }] },
            { kind: 'heading', level: 3, line: [text('Costs')] },
        ]
        await renderRouted(<GuideText blocks={blocks} page="overview" />, { at: '/guide/overview' })

        expect(screen.getByRole('heading', { level: 2 }).id).toBe('the-rail-at-a-glance')
        expect(screen.getByRole('heading', { level: 3 }).id).toBe('costs')
        const self = screen.getByRole('link', { name: 'Link to The rail, at a glance' })
        expect(self.getAttribute('href')).toBe('/guide/overview#the-rail-at-a-glance')
        expect(screen.getByRole('link', { name: 'Link to Costs' }).getAttribute('href')).toBe('/guide/overview#costs')
    })

    it('links to a page of the guide or a section of the app in the app, and to the web in a new tab', async () => {
        const line: GuidePiece[] = [
            { kind: 'link', text: 'signing in', target: { kind: 'page', page: 'signing-in', hash: 'the-secret' } },
            text(', '),
            { kind: 'link', text: 'the workspace', target: { kind: 'section', to: '/workspace' } },
            text(', '),
            { kind: 'link', text: 'the docs', target: { kind: 'web', href: 'https://docs.example.test/' } },
        ]
        await renderRouted(<GuideText blocks={[{ kind: 'paragraph', lines: [line] }]} page="overview" />)

        const page = screen.getByRole('link', { name: 'signing in' })
        expect(page.getAttribute('href')).toBe('/guide/signing-in#the-secret')
        expect(page.getAttribute('target')).toBeNull()
        const section = screen.getByRole('link', { name: 'the workspace' })
        expect(section.getAttribute('href')).toBe('/workspace')
        expect(section.getAttribute('target')).toBeNull()
        const web = screen.getByRole('link', { name: 'the docs' })
        expect(web.getAttribute('href')).toBe('https://docs.example.test/')
        expect(web.getAttribute('target')).toBe('_blank')
        expect(web.getAttribute('rel')).toBe('noreferrer noopener')
    })

    it('lays out a quote, a rule, a table, and emphasis', async () => {
        const blocks: Block<GuidePiece>[] = [
            { kind: 'quote', blocks: [{ kind: 'paragraph', lines: [[{ kind: 'em', text: 'Measure twice.' }]] }] },
            { kind: 'rule' },
            {
                kind: 'table',
                align: [undefined, 'right'],
                head: [[text('Key')], [text('Default')]],
                rows: [[[text('a')], [text('2')]]],
            },
        ]
        await renderRouted(<GuideText blocks={blocks} page="overview" />)

        expect(screen.getByRole('blockquote').textContent).toBe('Measure twice.')
        expect(screen.getByRole('emphasis').textContent).toBe('Measure twice.')
        expect(screen.getByRole('separator')).toBeDefined()
        expect(screen.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual(['Key', 'Default'])
        expect(screen.getAllByRole('cell').map((cell) => cell.textContent)).toEqual(['a', '2'])
    })

    it('colors a code block by the language its fence names, its characters as written', async () => {
        const lines = ['# The policy', '[policy]', 'max_resume_attempts = 2']
        const { container } = await renderRouted(
            <GuideText blocks={[{ kind: 'code', lines, lang: 'toml' }]} page="config-files" />,
        )

        // Once the grammar has read it, the comment is a piece of its own.
        expect(await screen.findByText('# The policy')).toBeTruthy()
        expect(container.textContent).toBe(lines.join('\n'))
    })

    it('leaves a code block in no language canopy highlights as written', async () => {
        const lines = ['lorem ipsum --dolor', 'amet']
        const { container } = await renderRouted(
            <GuideText blocks={[{ kind: 'code', lines, lang: 'text' }]} page="overview" />,
        )

        expect(container.textContent).toBe(lines.join('\n'))
    })
})

describe('GuideLines', () => {
    it('reads a paragraph written across lines as one, its line breaks as spaces', async () => {
        const { container } = await renderRouted(
            <GuideLines
                lines={[[text('The loop runs')], [{ kind: 'strong', text: 'one tick' }, text(' at a time.')]]}
            />,
        )
        expect(container.textContent).toBe('The loop runs one tick at a time.')
    })
})
