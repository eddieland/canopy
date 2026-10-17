import { describe, expect, it } from 'vitest'

import { anchor, GUIDE, guidePage, guideTarget, plainText } from './guide'
import type { GuidePage, GuidePiece } from './guide'
import type { Block, Line } from './rich-text'

// Every file in src/guide/, by its name without `.md`.
const FILES = Object.keys(import.meta.glob('../guide/*.md')).map((path) => path.replace(/^.*\/(.+)\.md$/u, '$1'))

describe('the guide', () => {
    it('lists every file in src/guide/ once, and nothing else', () => {
        expect(GUIDE.map((page) => page.slug).toSorted()).toEqual(FILES.toSorted())
    })

    it('reads each page as a title, a lead, and a body with no second title', () => {
        expect(GUIDE.flatMap((page) => shapeProblems(page))).toEqual([])
    })

    it('gives every heading on a page an anchor of its own', () => {
        expect(GUIDE.filter((page) => new Set(anchors(page.body)).size !== anchors(page.body).length)).toEqual([])
    })

    it('has no link that goes nowhere: each is read as a link, and every heading it names is there', () => {
        expect(GUIDE.flatMap((page) => linkProblems(page))).toEqual([])
    })
})

describe('guideTarget', () => {
    it('reads a page, a heading on a page or on this one, a section of the app, and the web', () => {
        expect(guideTarget('signing-in', 'overview')).toEqual({ kind: 'page', page: 'signing-in', hash: undefined })
        expect(guideTarget('signing-in#a-session', 'overview')).toEqual({
            kind: 'page',
            page: 'signing-in',
            hash: 'a-session',
        })
        expect(guideTarget('#the-rail', 'overview')).toEqual({ kind: 'page', page: 'overview', hash: 'the-rail' })
        expect(guideTarget('/runs', 'overview')).toEqual({ kind: 'section', to: '/runs' })
        expect(guideTarget('https://example.com/a', 'overview')).toEqual({
            kind: 'web',
            href: 'https://example.com/a',
        })
    })

    it('goes nowhere for a page the guide lacks, a path outside the sections, or another scheme', () => {
        expect(guideTarget('no-such-page', 'overview')).toBeUndefined()
        expect(guideTarget('/api/session', 'overview')).toBeUndefined()
        expect(guideTarget('javascript:alert(1)', 'overview')).toBeUndefined()
        expect(guideTarget('overview', 'overview')).toBeUndefined()
        expect(guideTarget('../README.md', 'overview')).toBeUndefined()
    })
})

describe('anchor', () => {
    it('makes a heading an id as GitHub does', () => {
        expect(anchor('The pages')).toBe('the-pages')
        expect(anchor("Acting from the UI's pages")).toBe('acting-from-the-uis-pages')
        expect(anchor('`canopy secret`, again')).toBe('canopy-secret-again')
    })
})

// What is wrong with a page's shape, each as `slug: problem`.
function shapeProblems(page: GuidePage): string[] {
    const problems: string[] = []
    if (page.title === page.slug) {
        problems.push(`${page.slug}: no # title on its first line`)
    }
    if (page.lead.length === 0) {
        problems.push(`${page.slug}: no lead paragraph under its title`)
    }
    if (page.body.some((block) => block.kind === 'heading' && block.level === 1)) {
        problems.push(`${page.slug}: a second # heading`)
    }
    return problems
}

// Each link on a page that goes nowhere, as `slug: what was written`.
function linkProblems(page: GuidePage): string[] {
    const pieces = [...page.lead, ...lines(page.body)].flat()
    const unread = pieces.flatMap((piece) =>
        piece.kind === 'text' ? [...piece.text.matchAll(/\[[^\]]+\]\([^)]*\)/gu)].map((match) => match[0]) : [],
    )
    const missing = pieces.flatMap((piece) => {
        if (piece.kind !== 'link' || piece.target.kind !== 'page' || piece.target.hash === undefined) {
            return []
        }
        const to = guidePage(piece.target.page)
        return anchors(to?.body ?? []).includes(piece.target.hash) ? [] : [`#${piece.target.hash}`]
    })
    return [...unread, ...missing].map((link) => `${page.slug}: ${link}`)
}

function lines(blocks: Block<GuidePiece>[]): Line<GuidePiece>[] {
    return blocks.flatMap((block) => {
        if (block.kind === 'paragraph') {
            return block.lines
        }
        if (block.kind === 'heading') {
            return [block.line]
        }
        return block.kind === 'list' ? block.items.flatMap((item) => item.lines) : []
    })
}

function anchors(blocks: Block<GuidePiece>[]): string[] {
    return blocks.flatMap((block) => (block.kind === 'heading' ? [anchor(plainText(block.line))] : []))
}
