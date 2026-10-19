import { describe, expect, it } from 'vitest'

import {
    anchor,
    EMBEDS,
    GUIDE,
    GUIDE_GROUPS,
    guideFor,
    guideNeighbours,
    guidePage,
    guideTarget,
    PAGE_GUIDES,
    plainText,
} from './guide'
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

    it('shows each example file whole, as a code block of its lines, and the rest of the page after it', () => {
        const code = guidePage('config-files')?.body.flatMap((block) => (block.kind === 'code' ? [block.lines] : []))
        const files = Object.values(EMBEDS).map((file) => file.replace(/\n$/u, '').split('\n'))
        expect(code).toEqual(files)
        expect(guidePage('config-files')?.body.at(-1)?.kind).toBe('paragraph')
    })

    it('leaves a fence naming no example file as written', () => {
        expect(
            GUIDE.flatMap((page) => page.body).filter((block) => block.kind === 'code' && block.lines.length === 0),
        ).toEqual([])
    })
})

describe('guideNeighbours', () => {
    it("walks the pages in the sidebar's order, across groups, with none before the first or after the last", () => {
        const order = GUIDE_GROUPS.flatMap((group) => group.pages.map((page) => page.slug))
        expect(GUIDE.map((page) => page.slug)).toEqual(order)
        const walked = GUIDE.map((page) => {
            const { previous, next } = guideNeighbours(page.slug)
            return [previous?.slug, next?.slug]
        })
        expect(walked).toEqual(order.map((_, i) => [order[i - 1], order[i + 1]]))
        expect(guideNeighbours('no-such-page')).toEqual({ previous: undefined, next: undefined })
    })
})

describe('guideFor', () => {
    it('opens a page of the guide for every route it names, at a heading that is there', () => {
        const problems = Object.entries(PAGE_GUIDES).flatMap(([route, ref]) => {
            const guide = guideFor(route as keyof typeof PAGE_GUIDES)
            if (guide === undefined) {
                return [`${route}: no page ${ref}`]
            }
            return guide.hash === undefined || anchors(guide.page.body).includes(guide.hash) ? [] : [`${route}: ${ref}`]
        })
        expect(problems).toEqual([])
    })

    it('opens a page at its top, or at the heading about the route', () => {
        expect(guideFor('/runs/')).toEqual({ page: guidePage('runs'), hash: undefined })
        expect(guideFor('/runs/$id')).toEqual({ page: guidePage('runs'), hash: 'a-runs-page' })
    })

    it('has none for the root, the guide, or no route at all', () => {
        expect(guideFor('__root__')).toBeUndefined()
        expect(guideFor('/guide/$page')).toBeUndefined()
        expect(guideFor(undefined)).toBeUndefined()
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
