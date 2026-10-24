import { readFile } from 'node:fs/promises'

import { expect } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

import { E2E_SECRET } from './secret.ts'

/** Where the page keeps the theme preference: the same key as src/theme/store.ts. */
export const STORAGE_KEY = 'canopy-theme'
/** Each theme's palettes besides its default (lavender, indigo), as src/theme/palette.ts names them. */
export const OTHER_PALETTES = {
    light: ['off-white', 'sage', 'solarized', 'nord', 'gruvbox', 'rose-pine'],
    dark: ['grey', 'black', 'forest', 'plum', 'solarized', 'gruvbox', 'monokai'],
} as const
/** Where the page keeps each theme's palette: the same key as src/theme/palette.ts. */
export const PALETTE_KEY = 'canopy-palette'
/** Every page, by its path and any query; a screenshot each in dark, of its main pane alone unless in WHOLE_ROUTES. */
export const ROUTES = [
    'attention',
    'runs',
    'runs/39',
    'runs/41',
    'worktrees',
    'tickets',
    'tickets/ABC-102',
    'tickets/ABC-105',
    'tickets/ABC-105/plan',
    'tasks',
    'tasks/1',
    'tasks/4',
    'tasks/1/runs/1',
    'pull-requests',
    `pull-requests/pr?url=${encodeURIComponent('https://github.com/acme/web/pull/88')}`,
    'reviews',
    'reviews/4',
    'reviews/4/run',
    'reviews/5',
    'chores',
    'chores/deps',
    'chores/deps/runs/2',
    'ticks',
    'ticks/2',
    'spend',
    'settings',
    'settings/limits',
    'search?q=web',
    'plan-editor',
    'memory',
    'guide/overview',
] as const
/** A page in ROUTES. */
export type Route = (typeof ROUTES)[number]
/**
 * The pages screenshotted whole, the shell included: the ones README.md shows. The rest show their main pane alone, so
 * a change to the header or the rail rewrites these images and not every one.
 */
export const WHOLE_ROUTES: readonly Route[] = ['attention', 'tickets/ABC-102', 'runs/39', 'reviews/4', 'ticks/2']
/**
 * The pages screenshotted in light as well: the shell, a list, and a detail page. Both themes draw from the same
 * tokens, so a few pages in light catch a light token gone wrong without doubling every image.
 */
export const LIGHT_ROUTES: readonly Route[] = ['attention', 'runs', 'tickets/ABC-102']
/** The themes the app has; a page is screenshotted in light only if in LIGHT_ROUTES. */
export const THEMES = ['light', 'dark'] as const
/** Half an hour after the fixtures' T0 (canopy/serve/mock/): every age on a page is the same on every run. */
export const NOW = new Date('2026-10-08T12:30:00Z')

/**
 * Opens a repository picker by its button, whose name says what it chooses (`Filter by repository: api`), and returns
 * its list, which opens over the page, outside whatever holds the button.
 */
export async function openRepoPicker(button: Locator): Promise<Locator> {
    await button.click()
    return button.page().getByRole('listbox', { name: 'Repositories' })
}

/**
 * An ISO time as the page writes it on hover with the clock at its default (src/lib/time.ts `localTime`): the
 * browser's local date and 24-hour time to the second, `10/8/2026, 12:00:00` in en-US.
 */
export function hoverTime(page: Page, iso: string): Promise<string> {
    return page.evaluate(
        (at) =>
            new Intl.DateTimeFormat(undefined, {
                year: 'numeric',
                month: 'numeric',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hourCycle: 'h23',
            }).format(new Date(at)),
        iso,
    )
}

/** Stores `theme` before any page script runs, as if chosen on an earlier visit. */
export async function storeTheme(page: Page, theme: 'light' | 'dark'): Promise<void> {
    await page.addInitScript(
        ([key, value]) => {
            globalThis.localStorage.setItem(key, value)
        },
        [STORAGE_KEY, theme] as const,
    )
}

/** Stores `palette` as `theme`'s before any page script runs, as if picked on an earlier visit. */
export async function storePalette(page: Page, theme: 'light' | 'dark', palette: string): Promise<void> {
    await page.addInitScript(
        ([key, value]) => {
            globalThis.localStorage.setItem(key, value)
        },
        [PALETTE_KEY, JSON.stringify({ [theme]: palette })] as const,
    )
}

/** Signs the page's browser in with the listener secret, as the sign-in page does: the cookie lands in its context. */
export async function signIn(page: Page): Promise<void> {
    const response = await page.request.post('api/session', { data: { secret: E2E_SECRET } })
    expect(response.status()).toBe(200)
}

/** Waits until the page is fully settled: fonts loaded, header counters filled, stream connected. */
export async function settled(page: Page): Promise<void> {
    await page.evaluate(async () => {
        await document.fonts.ready
    })
    const readouts = page.getByTestId('live-readouts')
    await expect(readouts.locator('[data-slot=skeleton]')).toHaveCount(0)
    await expect(page.getByTestId('stream-status')).toHaveAttribute('data-status', 'open')
    await expect(page.locator('main [data-slot=skeleton]')).toHaveCount(0)
}

/** The narrowest window the whole rail takes its place in (`src/hooks/use-rail-mode.ts`); narrower, it is a strip. */
export const FULL_RAIL = 1024

/**
 * Sets the window `width` wide and waits for the rail to take its shape there, a strip under FULL_RAIL and whole from
 * it, so what is measured next is in the pane the rail leaves.
 */
export async function windowWidth(page: Page, width: number): Promise<void> {
    await page.setViewportSize({ width, height: page.viewportSize()?.height ?? 900 })
    await expect(page.getByTestId('rail-strip')).toHaveCount(width < FULL_RAIL ? 1 : 0)
}

/** Screenshots the whole page as `name`, the header and the rail included. */
export async function screenshotWhole(page: Page, name: string): Promise<void> {
    await growToPage(page)
    await expect(page).toHaveScreenshot(name)
}

/** Screenshots the page's main pane as `name`, without the header and the rail around it. */
export async function screenshotMain(page: Page, name: string): Promise<void> {
    await growToPage(page)
    await expect(page.locator('main')).toHaveScreenshot(name)
}

/**
 * Grows the window to the page's height. The page scrolls under the header, not the window (AppShell), so a capture
 * would stop at the window's foot.
 */
async function growToPage(page: Page): Promise<void> {
    const scroller = page.locator('[data-scroll-restoration-id=page]')
    const height = await scroller.evaluate((el) => el.getBoundingClientRect().top + el.scrollHeight)
    const viewport = page.viewportSize()
    if (viewport === null) {
        throw new Error('the page has no viewport to grow')
    }
    await page.setViewportSize({ width: viewport.width, height: Math.max(viewport.height, Math.ceil(height)) })
}

/**
 * Serves a placeholder guide in place of the real one: its groups, its pages, and their words, all Latin, with
 * `e2e/guide-specimen.md` at `slug` and every kind of block and link a page can have on it. The guide's screenshot is
 * taken so, to hold how a page is drawn and nothing the guide says: its words and its list of pages change in most UI
 * pull requests and would otherwise rewrite the image in each, and conflict on it. The guide's pages are compiled into
 * the app's script as one array, `` [{title:`Getting started`,pages:[[`overview`,`...`], ...]}, ...] ``, which is
 * swapped as the script is served. The specimen's title, `Lorem ipsum`, shows that the swap took.
 */
export async function placeholderGuide(page: Page, slug: string): Promise<void> {
    const specimen = await readFile(new URL('guide-specimen.md', import.meta.url), 'utf8')
    const guide = JSON.stringify([
        {
            title: 'Prima pars',
            pages: [
                ['dolor-sit', '# Dolor sit amet\n\nConsectetur adipiscing elit.'],
                [slug, specimen],
                ['consectetur', '# Consectetur adipiscing\n\nSed do eiusmod tempor.'],
            ],
        },
        {
            title: 'Secunda pars',
            pages: [
                ['incididunt', '# Incididunt ut labore\n\nEt dolore magna aliqua.'],
                ['minim-veniam', '# Ut enim ad minim veniam\n\nQuis nostrud exercitation.'],
            ],
        },
    ])
    await page.route('**/assets/*.js', async (route) => {
        const response = await route.fetch()
        const script = await response.text()
        const at = /\[\{title:`[^`]*`,pages:\[\[/u.exec(script)?.index
        const body = at === undefined ? script : script.slice(0, at) + guide + script.slice(arrayEnd(script, at))
        await route.fulfill({ response, body })
    })
}

// Where the array literal opening at `start` in `script` ends: the index after its closing bracket. Brackets inside a
// string or template literal are its characters, not the array's.
function arrayEnd(script: string, start: number): number {
    let depth = 0
    for (let i = start; i < script.length; i += 1) {
        const char = script[i] ?? ''
        if (char === '`' || char === '"' || char === "'") {
            i += 1
            while (i < script.length && script[i] !== char) {
                i += script[i] === '\\' ? 2 : 1
            }
        } else if ('[{('.includes(char)) {
            depth += 1
        } else if (']})'.includes(char)) {
            depth -= 1
            if (depth === 0) {
                return i + 1
            }
        }
    }
    throw new Error('the guide array in the app script never closes')
}

/**
 * Pads a ticket's decisions to `count`, cycling through the ones the mock records, as a long-lived ticket collects
 * them: the mock's are too few to fill a panel past its height.
 */
export async function padDecisions(page: Page, ticketKey: string, count: number): Promise<void> {
    await page.route(`**/api/tickets/${ticketKey}`, async (route) => {
        const response = await route.fetch()
        const body = (await response.json()) as { decisions: { id: number }[] }
        const recorded = body.decisions
        body.decisions = Array.from({ length: count }, (_, i) => ({ ...recorded[i % recorded.length], id: 1000 + i }))
        await route.fulfill({ response, json: body })
    })
}

/** Makes a ticket's conversation `count` messages long, its recorded ones over and over, so it scrolls. */
export async function padMessages(page: Page, ticketKey: string, count: number): Promise<void> {
    await page.route(`**/api/tickets/${ticketKey}`, async (route) => {
        const response = await route.fetch()
        const body = (await response.json()) as { messages: { id: number }[] }
        const recorded = body.messages
        body.messages = Array.from({ length: count }, (_, i) => ({ ...recorded[i % recorded.length], id: 1000 + i }))
        await route.fulfill({ response, json: body })
    })
}

/**
 * Makes canopy's lifetime spend `usd`, as `GET /api/spend` and the event stream report it, for the hat shop: the mock
 * has spent too little to buy a hat. The stream's messages are rewritten in the page, as each is read, since a stream
 * never ends for a route to read whole.
 */
export async function spentInAll(page: Page, usd: number): Promise<void> {
    await page.route('**/api/spend', async (route) => {
        const response = await route.fetch()
        const body = (await response.json()) as { total_usd: number | null }
        body.total_usd = usd
        await route.fulfill({ response, json: body })
    })
    await page.addInitScript((total) => {
        // The getter is only ever called with `.call` on an event, so it never loses its `this`.
        // oxlint-disable-next-line typescript/unbound-method
        const read = Object.getOwnPropertyDescriptor(MessageEvent.prototype, 'data')?.get
        Object.defineProperty(MessageEvent.prototype, 'data', {
            get(this: MessageEvent): unknown {
                const data: unknown = read?.call(this)
                if (!(this.target instanceof EventSource) || typeof data !== 'string') {
                    return data
                }
                const parsed = JSON.parse(data) as { type?: string; spend?: { total_usd: number | null } }
                if (parsed.type !== 'spend.updated' || parsed.spend === undefined) {
                    return data
                }
                parsed.spend.total_usd = total
                return JSON.stringify(parsed)
            },
        })
    }, usd)
}

/** A line of a review's diff, as the API sends it. */
export interface DiffLine {
    /** Whether it is added, deleted, or context. */
    kind: 'add' | 'del' | 'ctx'
    /** Its number on the old side, null for an added line. */
    old: number | null
    /** Its number on the new side, null for a deleted line. */
    new: number | null
    /** Its text. */
    text: string
}

/** A review's finding, as the API sends it. */
export interface DiffFinding {
    /** How much it matters. */
    severity: 'blocking' | 'major' | 'minor'
    /** Its title. */
    title: string
    /** Where it is, as the reviewer wrote it. */
    location: string
    /** What is wrong, as the reviewer wrote it. */
    detail: string
    /** The index of the diff's file it is on, null for none. */
    file: number | null
    /** The new-side line it is on, null for none the diff shows. */
    line: number | null
    /** Whether the operator dismissed it. */
    dismissed: boolean
}

/** A file of `count` added lines in one hunk, numbered from 1; `text` gives each its text by its number. */
export function diffFile(path: string, count: number, text: (n: number) => string) {
    const lines = Array.from({ length: count }, (_, i): DiffLine => ({
        kind: 'add',
        old: null,
        new: i + 1,
        text: text(i + 1),
    }))
    return { path, old_path: null, binary: false, hunks: [{ header: '', lines }] }
}

/** Serves review:4 with this diff and these findings, the rest of it as the mock journal has it. */
export async function serveReview(
    page: Page,
    files: ReturnType<typeof diffFile>[],
    findings: DiffFinding[],
): Promise<void> {
    await page.route('**/api/reviews/4', async (route) => {
        const response = await route.fetch()
        const body = (await response.json()) as Record<string, unknown>
        // The fields the API sends every finding, as it sends them for one no one dismissed, held, or answered.
        const sent = findings.map((f) => ({
            dismissed_reason: null,
            held: false,
            answer: null,
            answer_reason: null,
            ...f,
        }))
        await route.fulfill({ response, json: { ...body, findings: sent, diff: { files, truncated: true } } })
    })
}

/** The plan editor's document. */
export function plan(page: Page): Locator {
    return page.getByRole('textbox', { name: 'Plan', exact: true })
}

/**
 * What `select` and `clickIn` read of the plan's ProseMirror view, which Tiptap keeps on the element it draws in as
 * `editor`.
 */
interface PlanView {
    state: { selection: { from: number; to: number; head: number } }
    posAtDOM: (node: Node, offset: number) => number
    domAtPos: (pos: number) => { node: Node }
}

/**
 * Clicks `target`, an element in the plan, as the operator would, and waits for the editor to hold its cursor there: a
 * key pressed next moves on from it. A click that moves the focus into the plan races ProseMirror as `select` says, and
 * a loaded machine can lose it, the cursor put back where the editor had it; this clicks again until the editor holds
 * it.
 */
export async function clickIn(target: Locator): Promise<void> {
    await expect(async () => {
        await target.click()
        await expect.poll(() => target.evaluate(holdsCursor), { timeout: 250 }).toBe(true)
    }).toPass({ timeout: 5000 })
}

// Whether the plan's editor holds its cursor inside `element`.
function holdsCursor(element: Element): boolean {
    const root = element.closest('[contenteditable]') as (Element & { editor: { view: PlanView } }) | null
    if (root === null) {
        return false
    }
    const { view } = root.editor
    return element.contains(view.domAtPos(view.state.selection.head).node)
}

/**
 * Clicks just past the last character of `target`, an element in the plan, as the operator would to write on after it,
 * and waits for the editor to hold its cursor at the element's end. Not `clickIn` and End: End stops at the end of the
 * line the click lands on, which in an element that wraps need not be its last, and the editor reads the cursor End
 * moves on `selectionchange`, as it does a selection `select` makes, so a loaded machine can put it back where the
 * click left it. This clicks again until the editor holds it.
 */
export async function clickAtEnd(target: Locator): Promise<void> {
    await expect(async () => {
        await target.click({ position: await target.evaluate(endPoint) })
        await expect.poll(() => target.evaluate(holdsCursorAtEnd), { timeout: 250 }).toBe(true)
    }).toPass({ timeout: 5000 })
}

// Where in `element`, from its top left corner, a click puts the cursor after its last character: the last character's
// right half, on its line.
function endPoint(element: Element): { x: number; y: number } {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
    let last: Text | null = null
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
        if ((node.textContent ?? '') !== '') {
            last = node as Text
        }
    }
    if (last === null) {
        throw new Error('the element has no text to click after')
    }
    const range = document.createRange()
    range.setStart(last, last.length - 1)
    range.setEnd(last, last.length)
    const char = range.getBoundingClientRect()
    const box = element.getBoundingClientRect()
    return { x: char.right - box.left - 1, y: char.top + char.height / 2 - box.top }
}

// Whether the plan's editor holds its cursor, and nothing selected, at the end of `element`'s content.
function holdsCursorAtEnd(element: Element): boolean {
    const root = element.closest('[contenteditable]') as (Element & { editor: { view: PlanView } }) | null
    if (root === null) {
        return false
    }
    const { view } = root.editor
    const { from, to } = view.state.selection
    return from === to && from === view.posAtDOM(element, element.childNodes.length)
}

/**
 * Selects `text` inside the plan, as a drag over it would, and waits for the editor to hold it: a key pressed next acts
 * on these words, not the ones before. ProseMirror reads the page's selection on `selectionchange`, which the browser
 * fires later. When the selection moves the focus into the plan from outside it, ProseMirror also puts its own
 * selection back 20 ms on if it has not read the page's by then, which a loaded machine can make it miss: a drag gives
 * it all the time it needs, but a selection made at once does not, so this makes it again until the editor holds it.
 */
export async function select(page: Page, text: string): Promise<void> {
    await plan(page).evaluate(async (root, wanted) => {
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
        for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
            const at = node.textContent?.indexOf(wanted) ?? -1
            if (at !== -1) {
                const range = document.createRange()
                range.setStart(node, at)
                range.setEnd(node, at + wanted.length)
                const { view } = (root as typeof root & { editor: { view: PlanView } }).editor
                const from = view.posAtDOM(node, at)
                const held = (): boolean =>
                    view.state.selection.from === from && view.state.selection.to === from + wanted.length
                for (let tries = 0; tries < 5 && !held(); tries += 1) {
                    const selection = globalThis.getSelection()
                    selection?.removeAllRanges()
                    selection?.addRange(range)
                    // Long past ProseMirror's 20 ms, so a try it undid is seen as undone, not as still to come.
                    const until = performance.now() + 100
                    while (!held() && performance.now() < until) {
                        await new Promise((resolve) => {
                            setTimeout(resolve, 5)
                        })
                    }
                }
                if (!held()) {
                    throw new Error(`the plan did not take the selection of ${wanted}`)
                }
                return
            }
        }
        throw new Error(`no text node holds ${wanted}`)
    }, text)
}

/**
 * Checks the spend chart's axis on the page shown: each day or hour it names whole, as `Sep 13` or `14:00`, centered
 * under its bar within a pixel, and clear of the next name, at least `minimum` of them.
 */
export async function expectSpendAxisWhole(page: Page, minimum: number): Promise<void> {
    const chart = page.getByTestId('spend-chart')
    await expect(chart.getByTestId(/^spend-axis-/u).first()).toBeVisible()
    const names = await chart.getByTestId(/^spend-axis-/u).evaluateAll((elements) =>
        elements.map((el) => {
            const day = (el as HTMLElement).dataset['testid']?.replace('spend-axis-', '') ?? ''
            const box = el.getBoundingClientRect()
            const bar = document.querySelector(`[data-testid="spend-bar-${day}"]`)?.getBoundingClientRect()
            return {
                text: el.textContent,
                left: box.left,
                right: box.right,
                offCenter: Math.abs((box.left + box.right) / 2 - ((bar?.left ?? 0) + (bar?.right ?? 0)) / 2),
                cut: el.scrollWidth > el.clientWidth,
            }
        }),
    )
    expect(names.length).toBeGreaterThanOrEqual(minimum)
    for (const [i, name] of names.entries()) {
        expect(name.text).toMatch(/^(?:[A-Z][a-z]{2} \d{1,2}|\d{2}:00)$/u)
        expect(name.cut).toBe(false)
        expect(name.offCenter).toBeLessThanOrEqual(1)
        const next = names[i + 1]
        if (next !== undefined) {
            expect(next.left).toBeGreaterThan(name.right)
        }
    }
}
