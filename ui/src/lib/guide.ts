// The guide (ui/DESIGN.md, "The guide"): the operator's documentation, a page each, in `src/guide/` as Markdown that
// is bundled with the build. A page is read by the parser rich text uses (`parseWith`), which turns it into data that
// `GuideText` renders as React elements, never HTML. It is canopy's own text, not the journal's, so unlike agent text
// it reads labelled links too: to another page of the guide, to a section of the app, or to the web.

import exampleWorkspace from '../../../examples/canopy-workspace.toml?raw'
import exampleConfig from '../../../examples/config.toml?raw'
import attention from '@/guide/attention.md?raw'
import chores from '@/guide/chores.md?raw'
import codeReview from '@/guide/code-review.md?raw'
import configFiles from '@/guide/config-files.md?raw'
import glossary from '@/guide/glossary.md?raw'
import howTheLoopWorks from '@/guide/how-the-loop-works.md?raw'
import memory from '@/guide/memory.md?raw'
import overview from '@/guide/overview.md?raw'
import philosophy from '@/guide/philosophy.md?raw'
import plans from '@/guide/plans.md?raw'
import pullRequests from '@/guide/pull-requests.md?raw'
import reports from '@/guide/reports.md?raw'
import runs from '@/guide/runs.md?raw'
import settings from '@/guide/settings.md?raw'
import signingIn from '@/guide/signing-in.md?raw'
import slack from '@/guide/slack.md?raw'
import tasks from '@/guide/tasks.md?raw'
import tickets from '@/guide/tickets.md?raw'
import ticks from '@/guide/ticks.md?raw'
import { parseWith } from '@/lib/rich-text'
import type { Block, Inline, Line } from '@/lib/rich-text'
import { SECTIONS } from '@/lib/sections'
import type { Section } from '@/lib/sections'
import type { FileRoutesById } from '@/routeTree.gen'

/** Where a link in the guide goes: a page of it (at a heading, with `hash`), a section of the app, or the web. */
export type GuideTarget =
    | { kind: 'page'; page: string; hash: string | undefined }
    | { kind: 'section'; to: Section }
    | { kind: 'web'; href: string }

/** A piece of a line of the guide: rich text's pieces, and a labelled link. */
export type GuidePiece = Inline | { kind: 'link'; text: string; target: GuideTarget }

/** One of the guide's `##` headings: what it says, and the id a link to it names. */
export interface GuideHeading {
    /** The heading's anchor, from its words (`anchor`). */
    id: string
    /** The heading as written, without its `#`s. */
    text: string
}

/** One page of the guide, read from its file. */
export interface GuidePage {
    /** Its address under `/guide/`: the file's name without `.md`. */
    slug: string
    /** The group the sidebar lists it under, such as `Getting started`. */
    group: string
    /** Its `#` heading, the file's first line: the page's name in its header and in the guide's lists. */
    title: string
    /** The paragraph after the title: one or two sentences on what the page covers, under its header and in lists. */
    lead: Line<GuidePiece>[]
    /** The rest of the page, its headings at `##` and below. */
    body: Block<GuidePiece>[]
    /** Its `##` headings, in order: what the page's contents list. */
    headings: GuideHeading[]
}

/** A group of the guide's pages, as its sidebar lists them under a heading. */
export interface GuideGroup {
    /** The group's heading. */
    title: string
    /** Its pages, in order. */
    pages: GuidePage[]
}

// The guide's files by group, in the order its sidebar lists them, which is also the order Previous and Next walk.
// Every file in src/guide/ is here; a test fails on one left out.
const SOURCES: readonly { title: string; pages: readonly (readonly [string, string])[] }[] = [
    {
        title: 'Getting started',
        pages: [
            ['overview', overview],
            ['signing-in', signingIn],
            ['how-the-loop-works', howTheLoopWorks],
            ['philosophy', philosophy],
        ],
    },
    {
        title: 'Your work',
        pages: [
            ['attention', attention],
            ['tickets', tickets],
            ['plans', plans],
            ['tasks', tasks],
            ['pull-requests', pullRequests],
            ['code-review', codeReview],
        ],
    },
    {
        title: 'The loop',
        pages: [
            ['runs', runs],
            ['ticks', ticks],
            ['reports', reports],
            ['chores', chores],
            ['memory', memory],
            ['slack', slack],
            ['settings', settings],
        ],
    },
    {
        title: 'Reference',
        pages: [
            ['config-files', configFiles],
            ['glossary', glossary],
        ],
    },
]

/**
 * The guide's page about each page of the app, by its route id, as a link in the guide names it (`runs#a-runs-page`):
 * what the book in a page's header opens. Every route is here but those with no page of their own (the root and the
 * redirects) and the guide's, so a new route fails the type check until it names one; a test fails on a page or a
 * heading the guide lacks.
 */
export const PAGE_GUIDES = {
    '/attention': 'attention',
    '/tickets/': 'tickets',
    '/tickets/$key': 'tickets#a-tickets-page',
    '/tickets/$key_/plan': 'plans',
    '/plan-editor': 'plans',
    '/tasks/': 'tasks',
    '/tasks/$id': 'tasks#a-tasks-page',
    '/tasks/$id_/runs/$run': 'tasks#a-tasks-run',
    '/pull-requests/': 'pull-requests',
    '/pull-requests/pr': 'pull-requests#the-pull-requests-page',
    '/pull-requests/reviews/': 'pull-requests#the-reviews-page',
    '/pull-requests/reviews/$id': 'pull-requests#a-reviews-page',
    '/pull-requests/reviews/$id_/run': 'pull-requests#a-reviews-run',
    '/workspace/': 'runs#the-workspace-page',
    '/workspace/runs/': 'runs',
    '/workspace/runs/$id': 'runs#a-runs-page',
    '/workspace/worktrees': 'runs#worktrees',
    '/chores/': 'chores',
    '/chores/$name': 'chores#a-chores-page',
    '/chores/$name_/runs/$id': 'chores#a-chores-page',
    '/workspace/ticks/': 'ticks',
    '/workspace/ticks/$id': 'ticks#a-ticks-page',
    '/reports/': 'reports',
    '/reports/spend': 'reports#the-spend-page',
    '/reports/checklist': 'reports#the-checklist-page',
    '/reports/health': 'reports#the-health-page',
    '/reports/ci': 'reports#the-ci-page',
    '/reports/reviews': 'reports#the-reviews-page',
    '/memory': 'memory',
    '/search': 'overview#search',
    '/system': 'overview#system-resources',
    '/settings': 'settings',
    '/settings_/limits': 'settings#limits-and-trust',
    '/settings_/skills': 'settings#skills',
} as const satisfies Record<
    Exclude<
        keyof FileRoutesById,
        | '__root__'
        | '/'
        | '/spend'
        | '/reviews/'
        | '/reviews/$id'
        | '/reviews/$id_/run'
        | '/ticks/'
        | '/ticks/$id'
        | '/worktrees'
        | '/runs/'
        | '/runs/$id'
        | '/runs/ticks/'
        | '/runs/ticks/$id'
        | '/runs/worktrees'
        | '/guide/'
        | '/guide/$page'
    >,
    string
>

/**
 * The files a page of the guide shows whole, by the path its fence names after the language: the repository's own
 * examples, read when the guide is built, so the guide shows the files canopy ships rather than a copy that drifts. A
 * fence opens empty in the page, as ```` ```toml examples/config.toml ````, and the file is its body.
 */
export const EMBEDS: Readonly<Record<string, string>> = {
    'examples/canopy-workspace.toml': exampleWorkspace,
    'examples/config.toml': exampleConfig,
}

const SLUGS: ReadonlySet<string> = new Set(SOURCES.flatMap(({ pages }) => pages.map(([slug]) => slug)))
const PAGE_REF = /^([a-z0-9-]*)(?:#([a-z0-9-]+))?$/u
const WEB = /^https?:\/\/\S+$/u

/** The guide's groups, each with its pages, in the sidebar's order. */
export const GUIDE_GROUPS: readonly GuideGroup[] = SOURCES.map(({ title, pages }) => ({
    title,
    pages: pages.map(([slug, text]) => readPage(slug, title, text)),
}))

/** Every page of the guide, in the sidebar's order: the first is where `/guide` opens. */
export const GUIDE: readonly GuidePage[] = GUIDE_GROUPS.flatMap((group) => group.pages)

/** The page at `slug`, or undefined when the guide has none. */
export function guidePage(slug: string): GuidePage | undefined {
    return GUIDE.find((page) => page.slug === slug)
}

/** The pages before and after `slug` in the guide's order, across groups: what its Previous and Next open. */
export function guideNeighbours(slug: string): { previous: GuidePage | undefined; next: GuidePage | undefined } {
    const at = GUIDE.findIndex((page) => page.slug === slug)
    return { previous: at > 0 ? GUIDE[at - 1] : undefined, next: at === -1 ? undefined : GUIDE[at + 1] }
}

/** A route's page of the guide, at a heading of it or its top: where the book in that route's header goes. */
export interface GuideFor {
    /** The guide's page. */
    page: GuidePage
    /** The heading on it, or undefined for its top. */
    hash: string | undefined
}

/**
 * The guide's page about the route `routeId`, at the heading about it, or undefined for a route the guide has no page
 * about: the root, the 404, and the guide itself.
 */
export function guideFor(routeId: keyof FileRoutesById | undefined): GuideFor | undefined {
    const guides: Partial<Record<keyof FileRoutesById, string>> = PAGE_GUIDES
    const [slug = '', hash] = routeId === undefined ? [] : (guides[routeId]?.split('#') ?? [])
    const page = guidePage(slug)
    return page === undefined ? undefined : { page, hash }
}

/**
 * Where a link written as `href` on page `from` goes, or undefined when it goes nowhere the guide links: `overview`
 * or `overview#the-rail` is a page of the guide, `#the-rail` a heading on `from`, `/workspace` a section of the app,
 * and an http or https URL the web. A link to anything else is left as its characters.
 */
export function guideTarget(href: string, from: string): GuideTarget | undefined {
    if (WEB.test(href)) {
        return { kind: 'web', href }
    }
    if (href.startsWith('/')) {
        const to = SECTIONS.find((section) => section === href)
        return to === undefined ? undefined : { kind: 'section', to }
    }
    const ref = PAGE_REF.exec(href)
    if (ref === null) {
        return undefined
    }
    const page = ref[1] === '' || ref[1] === undefined ? from : ref[1]
    if (!SLUGS.has(page) || (page === from && ref[2] === undefined)) {
        return undefined
    }
    return { kind: 'page', page, hash: ref[2] }
}

/** A heading's anchor: its words in lower case, joined by hyphens, much as GitHub makes them for a Markdown file. */
export function anchor(text: string): string {
    return text
        .toLowerCase()
        .replaceAll(/[^a-z0-9\s_-]/gu, '')
        .trim()
        .replaceAll(/\s+/gu, '-')
}

/** A line's text with its markup dropped: what a heading's anchor and a page's title are made from. */
export function plainText(line: Line<GuidePiece>): string {
    return line.map((piece) => piece.text).join('')
}

function readPage(slug: string, group: string, text: string): GuidePage {
    const blocks = parseWith(embed(text), (line) => guideLine(line, slug))
    const [first, second, ...rest] = blocks
    const title = first?.kind === 'heading' && first.level === 1 ? plainText(first.line) : slug
    const lead = second?.kind === 'paragraph' ? second.lines : []
    const body = second?.kind === 'paragraph' ? rest : blocks.slice(1)
    const headings = body.flatMap((block) =>
        block.kind === 'heading' && block.level === 2
            ? [{ id: anchor(plainText(block.line)), text: plainText(block.line) }]
            : [],
    )
    return { slug, group, title, lead, body, headings }
}

/** `text` with each empty fence that names a file of `EMBEDS` filled with that file; any other is left as written. */
function embed(text: string): string {
    return text.replaceAll(/^(```\w+ (\S+)\n)```$/gmu, (fence: string, open: string, path: string) => {
        const file = EMBEDS[path]
        return file === undefined ? fence : `${open}${file.endsWith('\n') ? file : `${file}\n`}\`\`\``
    })
}

/** A line of a guide page on `slug`: `code`, **strong**, and `[text](href)`; a link going nowhere stays as written. */
function guideLine(text: string, slug: string): Line<GuidePiece> {
    const line: Line<GuidePiece> = []
    let last = 0
    for (const match of text.matchAll(/`([^`]+)`|\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/gu)) {
        if (match.index > last) {
            line.push({ kind: 'text', text: text.slice(last, match.index) })
        }
        line.push(guidePiece(match, slug))
        last = match.index + match[0].length
    }
    if (last < text.length) {
        line.push({ kind: 'text', text: text.slice(last) })
    }
    return line
}

function guidePiece(match: RegExpExecArray, slug: string): GuidePiece {
    const [written, code, strong, label, href] = match
    if (code !== undefined) {
        return { kind: 'code', text: code }
    }
    if (strong !== undefined) {
        return { kind: 'strong', text: strong }
    }
    const target = guideTarget(href ?? '', slug)
    return target === undefined ? { kind: 'text', text: written } : { kind: 'link', text: label ?? '', target }
}
