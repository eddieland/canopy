import { readFile } from 'node:fs/promises'

import { expect, test } from '@playwright/test'
import type { BrowserContext, Locator, Page } from '@playwright/test'

import { clickAtEnd, clickAtStart, plan, settled, signIn, storeTheme, writePlan } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
    await page.goto('plan-editor')
    await settled(page)
})

// Whether the code block that holds `target` is in sight: a diagram's code out of sight is still drawn, clipped to a
// pixel, for the caret and a screen reader, so Playwright counts it visible.
function inSight(target: Locator): Promise<boolean> {
    return target.evaluate((element) => (element.closest('pre')?.getBoundingClientRect().height ?? 0) > 1)
}

test("the sample plan's Mermaid block is drawn as its diagram, its source under Source", async ({ page }) => {
    const doc = plan(page)
    const diagram = doc.getByRole('img', { name: /^A sequence diagram/u })
    await expect(diagram).toBeVisible()
    expect(await diagram.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(100)
    const source = doc.getByText('participant Page as web: reports page')
    await expect.poll(() => inSight(source)).toBe(false)

    const toggle = doc.getByRole('button', { name: 'Source', exact: true })
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-pressed', 'true')
    await expect.poll(() => inSight(source)).toBe(true)
    await toggle.click()
    await expect.poll(() => inSight(source)).toBe(false)

    // The block is still its Markdown, written back as it was read.
    await page.getByRole('button', { name: 'Show Markdown' }).click()
    await expect(page.getByLabel('Plan Markdown')).toContainText('```mermaid\nsequenceDiagram\n    participant Page')
})

for (const theme of ['dark', 'light'] as const) {
    test(`a diagram's picture saves as a PNG twice its size, on its surface, in ${theme}`, async ({ page }) => {
        await storeTheme(page, theme)
        await page.reload()
        const block = plan(page).locator('.plan-diagram')
        const image = block.getByRole('img', { name: /^A sequence diagram/u })
        await expect(image).toBeVisible()
        const size = await image.evaluate((shown: HTMLImageElement) => [shown.naturalWidth, shown.naturalHeight])
        await block.hover()
        await block.getByRole('button', { name: 'Copy or save the picture' }).click()
        const saving = page.waitForEvent('download')
        await page.getByRole('menuitem', { name: 'Save as PNG' }).click()
        const download = await saving
        expect(download.suggestedFilename()).toBe('plan-sequence-1.png')
        await expect(page.getByRole('status').filter({ hasText: 'Saved the diagram as a PNG' })).toBeVisible()

        const png = await readFile(await download.path())
        expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual(size.map((side) => side * 2))
        // Its corner is the surface, opaque: dark on a dark page, light on a light one.
        const [red = 0, green = 0, blue = 0, alpha = 0] = await page.evaluate(async (base64) => {
            const bytes = Uint8Array.from(atob(base64), (char) => char.codePointAt(0) ?? 0)
            const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/png' }))
            const context = new OffscreenCanvas(1, 1).getContext('2d')
            context?.drawImage(bitmap, 0, 0)
            return [...(context?.getImageData(0, 0, 1, 1).data ?? [])]
        }, png.toString('base64'))
        expect(alpha).toBe(255)
        expect(red + green + blue)[theme === 'dark' ? 'toBeLessThan' : 'toBeGreaterThan'](theme === 'dark' ? 200 : 600)
    })
}

// Saves the picture of `block`, a diagram's code block, as an SVG, and gives back its file's name, path, and text.
async function saveSvg(page: Page, block: Locator): Promise<{ name: string; path: string; svg: string }> {
    await block.hover()
    await block.getByRole('button', { name: 'Copy or save the picture' }).click()
    const saving = page.waitForEvent('download')
    await page.getByRole('menuitem', { name: 'Save as SVG' }).click()
    const download = await saving
    const path = await download.path()
    return { name: download.suggestedFilename(), path, svg: await readFile(path, 'utf8') }
}

// What the file at `path` does opened on its own, in a tab of `context`: how large it draws, whether anything in it
// ran, and what it asked for besides itself.
async function openOnItsOwn(
    context: BrowserContext,
    path: string,
): Promise<{ width: number; height: number; ran: boolean; fetched: string[] }> {
    const tab = await context.newPage()
    const fetched: string[] = []
    tab.on('request', (request) => {
        if (request.url() !== `file://${path}`) {
            fetched.push(request.url())
        }
    })
    await tab.goto(`file://${path}`)
    const seen = await tab.evaluate(() => {
        const box = document.documentElement.getBoundingClientRect()
        return { width: box.width, height: box.height, ran: 'pwned' in globalThis }
    })
    await tab.close()
    return { ...seen, fetched }
}

test('every kind of diagram saves as an SVG with nothing left out, which draws on its own', async ({
    page,
    context,
}) => {
    const kinds = [
        [
            'flowchart',
            ['flowchart TD', '  A["Dispatch (new)"] -->|"calls"| B[Runner]', '  subgraph web', '    B', '  end'],
        ],
        [
            'sequence',
            ['sequenceDiagram', '  A->>B: hi', '  loop each row', '    B-->>A: row', '  end', '  Note over A,B: done'],
        ],
        ['state', ['stateDiagram-v2', '  [*] --> ready', '  ready --> running: dispatch', '  running --> [*]']],
        ['class', ['classDiagram', '  class Run {', '    +str status', '    +start()', '  }', '  Run --> Ticket']],
        ['er', ['erDiagram', '  TICKET ||--o{ RUN : has', '  RUN {', '    int id', '  }']],
    ] as const
    await writePlan(page, ['# Plan', ...kinds.flatMap(([, lines]) => ['', '```mermaid', ...lines, '```'])].join('\n'))
    const blocks = plan(page).locator('.plan-diagram')
    await expect(blocks.locator('img:visible')).toHaveCount(kinds.length)
    for (const [i, [kind]] of kinds.entries()) {
        const block = blocks.nth(i)
        const shown = decodeURIComponent((await block.getByRole('img').getAttribute('src')) ?? '').replace(
            /^[^,]*,/u,
            '',
        )
        const saved = await saveSvg(page, block)
        expect(saved.name).toBe(`plan-${kind}-${i + 1}.svg`)
        // Every element it draws, each with every attribute it had, its stylesheet whole, and a background under them.
        const [drawn = [], kept = []] = await page.evaluate(
            (pictures: string[]) =>
                pictures.map((svg) =>
                    [...new DOMParser().parseFromString(svg, 'image/svg+xml').querySelectorAll('*')].map(
                        (element) =>
                            `${element.localName}[${element.getAttributeNames().toSorted().join(' ')}]${
                                element.localName === 'style' ? element.textContent : ''
                            }`,
                    ),
                ),
            [shown, saved.svg],
        )
        expect(kept).toEqual([drawn[0], 'rect[fill height width x y]', ...drawn.slice(1)])
        const opened = await openOnItsOwn(context, saved.path)
        expect(opened.width).toBeGreaterThan(50)
        expect(opened.fetched).toEqual([])
    }
})

test('a diagram whose labels write HTML and whose config asks for links saves as an inert SVG', async ({
    page,
    context,
}) => {
    await writePlan(
        page,
        [
            '# Plan',
            '',
            '```mermaid',
            '---',
            'config:',
            '  securityLevel: loose',
            '  htmlLabels: true',
            '---',
            'flowchart LR',
            '  A["<img src=pwned.png onerror=window.pwned=1>"] --> B["<b>bold</b>"]',
            '  click A call pwn()',
            '  click B href "javascript:window.pwned=2"',
            '  C[docs] --> A',
            '  click C href "https://example.com/elsewhere"',
            '```',
            '',
        ].join('\n'),
    )
    const block = plan(page).locator('.plan-diagram')
    await expect(block.getByRole('img', { name: /^A flowchart/u })).toBeVisible()
    const saved = await saveSvg(page, block)
    expect(saved.svg).not.toMatch(/<a\b|onerror|<script|foreignObject|javascript:|example\.com/iu)
    const opened = await openOnItsOwn(context, saved.path)
    expect(opened.ran).toBe(false)
    expect(opened.fetched).toEqual([])
    expect(opened.width).toBeGreaterThan(50)
})

test.describe("a diagram's actions", () => {
    test.use({ permissions: ['clipboard-read', 'clipboard-write'] })

    test('copy its Mermaid source as the plan holds it between its fence lines, edits included', async ({ page }) => {
        const doc = plan(page)
        const block = doc.locator('.plan-diagram')
        const copy = block.getByRole('button', { name: 'Copy Mermaid source' })
        await expect(copy.locator('..')).toHaveCSS('opacity', '0')
        await block.hover()
        await expect(copy.locator('..')).toHaveCSS('opacity', '1')
        await copy.click()
        await expect(page.getByRole('status').filter({ hasText: 'Copied Mermaid source' })).toBeVisible()
        const copied = await page.evaluate(() => navigator.clipboard.readText())

        await page.getByRole('button', { name: 'Show Markdown' }).click()
        const markdown = (await page.getByLabel('Plan Markdown').textContent()) ?? ''
        const fenced = /```mermaid\n(?<source>[\s\S]*?)\n```/u.exec(markdown)?.groups?.['source']
        expect(copied).toBe(fenced)

        // An edit to its code is what it copies next, while the caret is in it, which shows its actions too.
        await clickAtStart(doc.getByRole('heading', { name: 'Files' }))
        await page.keyboard.press('ArrowLeft')
        await page.keyboard.type('\nPage->>Page: done')
        // The caret alone shows them: the pointer is away from the block.
        await page.mouse.move(0, 0)
        await expect(copy.locator('..')).toHaveCSS('opacity', '1')
        await copy.click()
        await expect
            .poll(() => page.evaluate(() => navigator.clipboard.readText()))
            .toBe(`${fenced}\nPage->>Page: done`)
    })

    test('copy its picture as an image, a PNG on the clipboard', async ({ page }) => {
        const block = plan(page).locator('.plan-diagram')
        await expect(block.getByRole('img', { name: /^A sequence diagram/u })).toBeVisible()
        await block.hover()
        await block.getByRole('button', { name: 'Copy or save the picture' }).click()
        await page.getByRole('menuitem', { name: 'Copy as image' }).click()
        await expect(page.getByRole('status').filter({ hasText: 'Copied the diagram as an image' })).toBeVisible()
        const types = await page.evaluate(async () => (await navigator.clipboard.read()).flatMap((item) => item.types))
        expect(types).toContain('image/png')
    })

    test('copy the source of one that cannot be drawn', async ({ page }) => {
        await writePlan(page, '# Plan\n\n```mermaid\npie\n  "a": 1\n```\n')
        const block = plan(page).locator('.plan-diagram')
        await expect(block.getByText(/^Not drawn/u)).toBeVisible()
        await block.hover()
        await block.getByRole('button', { name: 'Copy Mermaid source' }).click()
        await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('pie\n  "a": 1')
    })
})

test('the caret moved into a diagram shows its source, and an edit there draws it again', async ({ page }) => {
    const doc = plan(page)
    const diagram = doc.getByRole('img', { name: /^A sequence diagram/u })
    await expect(diagram).toBeVisible()
    const before = await diagram.getAttribute('src')
    const source = doc.getByText('participant Page as web: reports page')
    await expect.poll(() => inSight(source)).toBe(false)

    // From the start of the heading after it, back into the end of its code, as the keyboard goes.
    await clickAtStart(doc.getByRole('heading', { name: 'Files' }))
    await page.keyboard.press('ArrowLeft')
    await expect.poll(() => inSight(source)).toBe(true)
    await page.keyboard.type('\nPage->>Page: says it is done')
    await expect(diagram).not.toHaveAttribute('src', before ?? '')
    await expect(diagram).toBeVisible()

    // Out of it again, the diagram is all there is.
    await doc.getByRole('heading', { name: 'Files' }).click()
    await expect.poll(() => inSight(source)).toBe(false)
})

test("the arrow keys go into a diagram's code from the line above and below it", async ({ page }) => {
    const doc = plan(page)
    await expect(doc.getByRole('img', { name: /^A sequence diagram/u })).toBeVisible()
    const source = doc.getByText('participant Page as web: reports page')

    // Down from the end of the paragraph above, to the start of its code.
    await clickAtEnd(doc.locator('p', { hasText: 'which the route uses.' }))
    await page.keyboard.press('ArrowDown')
    await expect.poll(() => inSight(source)).toBe(true)
    await page.keyboard.type('%% the export, row by row\n')

    // Up from the heading below, to the end of its code.
    await clickAtStart(doc.getByRole('heading', { name: 'Files' }))
    await expect.poll(() => inSight(source)).toBe(false)
    await page.keyboard.press('ArrowUp')
    await expect.poll(() => inSight(source)).toBe(true)
    await page.keyboard.type('\nPage->>Page: done')

    await page.getByRole('button', { name: 'Show Markdown' }).click()
    const markdown = page.getByLabel('Plan Markdown')
    await expect(markdown).toContainText('```mermaid\n%% the export, row by row\nsequenceDiagram')
    await expect(markdown).toContainText('    end\nPage->>Page: done\n```')
})

test("a class diagram and an entity relationship diagram are drawn, for a plan's types and tables", async ({
    page,
}) => {
    await writePlan(
        page,
        [
            '# Plan',
            '',
            '```mermaid',
            'classDiagram',
            '  class Run {',
            '    +str status',
            '  }',
            '  Run --> Ticket',
            '```',
            '',
            '```mermaid',
            'erDiagram',
            '  TICKET ||--o{ RUN : has',
            '```',
            '',
        ].join('\n'),
    )
    const doc = plan(page)
    for (const name of [/^A class diagram/u, /^An entity relationship diagram/u]) {
        const diagram = doc.getByRole('img', { name })
        await expect(diagram).toBeVisible()
        expect(await diagram.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(50)
    }
})

test('a diagram mermaid cannot read, or of a kind not drawn here, shows its source and why', async ({ page }) => {
    await writePlan(
        page,
        '# Plan\n\n```mermaid\nflowchart LR\n  A -->\n```\n\n```mermaid\npie\n  "a": 1\n```\n\n' +
            '```mermaid\nrequirementDiagram\n  requirement r {\n    id: 1\n  }\n```\n',
    )
    const doc = plan(page)
    await expect(doc.getByText(/^Not drawn: Parse error on line/u)).toBeVisible()
    await expect(doc.getByText('Not drawn: pie is not drawn here, only flowchart, sequenceDiagram')).toBeVisible()
    // Named as the planner wrote it, not as mermaid calls it inside (`requirement`).
    await expect(doc.getByText('Not drawn: requirementDiagram is not drawn here', { exact: false })).toBeVisible()
    await expect(doc.getByText('A -->')).toBeVisible()
    await expect(doc.getByText('"a": 1')).toBeVisible()
    await expect(doc.getByRole('img')).toHaveCount(0)
})

test('a diagram that writes a link is drawn, its node as any other and no link in its picture', async ({ page }) => {
    await writePlan(
        page,
        [
            '# Plan',
            '',
            '```mermaid',
            'flowchart LR',
            '  A[canopy docs] --> B[api]',
            '  click A href "https://example.com/not-the-docs" "a tooltip"',
            '  click B "https://example.org/other" _blank',
            '```',
            '',
        ].join('\n'),
    )
    const diagram = plan(page).getByRole('img', { name: /^A flowchart/u })
    await expect(diagram).toBeVisible()
    await expect.poll(() => diagram.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(100)
    const svg = decodeURIComponent((await diagram.getAttribute('src')) ?? '')
    expect(svg).toContain('>canopy<')
    expect(svg).not.toMatch(/<a\b/u)
    expect(svg).not.toContain('example.com')
    expect(svg).not.toContain('example.org')
    await expect(plan(page).getByText(/^Not drawn/u)).toHaveCount(0)
})

test("what a diagram's labels write as HTML stays text, and its config cannot say otherwise", async ({ page }) => {
    const fetched: string[] = []
    page.on('request', (request) => {
        if (new URL(request.url()).pathname.endsWith('/pwned.png')) {
            fetched.push(request.url())
        }
    })
    await writePlan(
        page,
        [
            '# Plan',
            '',
            '```mermaid',
            '---',
            'config:',
            '  securityLevel: loose',
            '  htmlLabels: true',
            '---',
            'flowchart LR',
            '  A["<img src=pwned.png onerror=window.pwned=1>"] --> B["<b>bold</b>"]',
            '  click A call pwn()',
            '```',
            '',
        ].join('\n'),
    )
    const diagram = plan(page).getByRole('img', { name: /^A flowchart/u })
    await expect(diagram).toBeVisible()
    const svg = decodeURIComponent((await diagram.getAttribute('src')) ?? '')
    expect(svg).not.toContain('foreignObject')
    expect(svg).not.toContain('onerror')
    expect(await page.evaluate(() => 'pwned' in globalThis)).toBe(false)
    expect(fetched).toEqual([])
})

test('a diagram too wide to read narrowed scrolls instead, its far edge faded', async ({ page }) => {
    const chain = Array.from({ length: 12 }, (_, i) => `N${i}[Step ${i} of the export]`).join(' --> ')
    await writePlan(page, `# Plan\n\n\`\`\`mermaid\nflowchart LR\n    ${chain}\n\`\`\`\n`)
    const diagram = plan(page).getByRole('img', { name: /^A flowchart/u })
    await expect(diagram).toBeVisible()
    const shown = await diagram.evaluate((image: HTMLImageElement) => ({
        drawn: image.naturalWidth,
        shown: image.getBoundingClientRect().width,
        room: image.parentElement?.clientWidth ?? 0,
    }))
    // Wider than the plan, so it is not shown whole; but at three quarters of its size at least, not shrunk to fit.
    expect(shown.drawn).toBeGreaterThan(shown.room / 0.75)
    expect(shown.shown).toBeGreaterThanOrEqual(Math.floor(shown.drawn * 0.75))

    const scroll = diagram.locator('xpath=..')
    await expect(scroll).toHaveAttribute('data-more-end')
    await expect(scroll).not.toHaveAttribute('data-more-start')
    await scroll.evaluate((box) => {
        box.scrollLeft = box.scrollWidth
    })
    await expect(scroll).toHaveAttribute('data-more-start')
    await expect(scroll).not.toHaveAttribute('data-more-end')
})

test('a diagram that fits is drawn at its own size, not stretched', async ({ page }) => {
    await writePlan(page, '# Plan\n\n```mermaid\nflowchart LR\n    A[web] --> B[api]\n```\n')
    const diagram = plan(page).getByRole('img', { name: /^A flowchart/u })
    await expect(diagram).toBeVisible()
    const width = await diagram.evaluate((image: HTMLImageElement) => ({
        drawn: image.naturalWidth,
        shown: image.getBoundingClientRect().width,
    }))
    expect(Math.abs(width.shown - width.drawn)).toBeLessThan(1)
    await expect(diagram.locator('xpath=..')).not.toHaveAttribute('data-more-end')
})
