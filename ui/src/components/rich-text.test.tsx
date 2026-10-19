import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderRouted } from '@/test-utils'

import { InlineCode, RichText } from './rich-text'

afterEach(() => {
    cleanup()
})

const PR = 'https://github.com/acme/web/pull/88'
const SEVEN_LINES = ['one', 'two', 'three', 'four', 'five', 'six', 'seven'].join('\n')

describe('RichText', () => {
    it('shows its first lines and a toggle for the rest, which opens and closes them', () => {
        render(<RichText text={SEVEN_LINES} lines={4} />)
        const toggle = screen.getByRole('button', { name: 'show 3 more lines', expanded: false })
        expect(screen.getByText(/four/u)).toBeDefined()
        expect(screen.queryByText(/five/u)).toBeNull()

        fireEvent.click(toggle)
        expect(screen.getByRole('button', { name: 'show less', expanded: true })).toBeDefined()
        expect(screen.getByText(/seven/u)).toBeDefined()

        fireEvent.click(toggle)
        expect(screen.getByRole('button', { name: 'show 3 more lines', expanded: false })).toBeDefined()
        expect(screen.queryByText(/five/u)).toBeNull()
    })

    it('shows text one line over whole, as a toggle would take the line it saves, and all of it without lines', () => {
        const fiveLines = SEVEN_LINES.split('\n').slice(0, 5).join('\n')
        const { rerender } = render(<RichText text={fiveLines} lines={4} />)
        expect(screen.queryByRole('button')).toBeNull()
        expect(screen.getByText(/five/u)).toBeDefined()

        rerender(<RichText text={SEVEN_LINES} />)
        expect(screen.queryByRole('button')).toBeNull()
        expect(screen.getByText(/seven/u)).toBeDefined()
    })

    it('folds one long paragraph as it folds many lines, cut where a word ends', () => {
        const long = Array.from({ length: 80 }, (_, i) => `word${i}`).join(' ')
        render(<RichText text={long} lines={2} />)
        expect(screen.getByRole('button', { name: /^show \d+ more lines$/u, expanded: false })).toBeDefined()
        expect(screen.getByText(/word10 .*…$/u)).toBeDefined()
        expect(screen.queryByText(/word79/u)).toBeNull()
    })

    it("lays out an agent's lists, headings, and code, its markup as characters and only bare URLs linked", () => {
        const text = [
            '## What changed',
            '- **Export** writes [CSV](https://evil.test) <b>now</b>',
            '- see https://ci.example.test/7 and `https://not.linked.test`',
            '```',
            '<script>alert(1)</script>',
            '```',
        ].join('\n')
        render(<RichText text={text} />)

        expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
            'Export writes [CSV](https://evil.test) <b>now</b>',
            'see https://ci.example.test/7 and https://not.linked.test',
        ])
        expect(screen.getByText('What changed')).toBeDefined()
        expect(screen.getByText('<script>alert(1)</script>')).toBeDefined()
        expect(screen.getByRole('strong').textContent).toBe('Export')
        expect(screen.getByRole('code').textContent).toBe('https://not.linked.test')
        expect(screen.getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual([
            'https://evil.test',
            'https://ci.example.test/7',
        ])
    })
})

describe('InlineCode', () => {
    it('sets code spans as code, links the URLs outside them, and names a PR as the PR is anywhere', async () => {
        await renderRouted(
            <InlineCode text={`opened ${PR}; CI at https://ci.example.test/7; run \`canopy show https://x.test\``} />,
        )
        expect(screen.getByRole('code').textContent).toBe('canopy show https://x.test')
        expect(screen.getByRole('link', { name: 'acme/web#88' })).toBeDefined()
        expect(screen.getByRole('link', { name: 'acme/web#88 on GitHub' }).getAttribute('href')).toBe(PR)
        expect(screen.getByRole('link', { name: 'https://ci.example.test/7' }).getAttribute('target')).toBe('_blank')
        expect(screen.getAllByRole('link')).toHaveLength(3)
    })

    it('links the runs harness text names to their pages', async () => {
        await renderRouted(<InlineCode text="run:40 (fix-ci) ended failed; log runs/40.log" />)
        expect(screen.getByRole('link', { name: 'run:40' }).getAttribute('href')).toBe('/runs/40')
        expect(screen.getAllByRole('link')).toHaveLength(1)
    })

    it('links nothing inside an element that is already a link, and still names a PR', () => {
        const { container } = render(
            <InlineCode text={`run:40 opened ${PR}; CI at https://ci.example.test/7`} links={false} />,
        )
        expect(screen.queryByRole('link')).toBeNull()
        expect(container.textContent).toBe('run:40 opened acme/web#88; CI at https://ci.example.test/7')
    })
})
