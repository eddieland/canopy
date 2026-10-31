import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

import { plan, settled, signIn } from './helpers.ts'

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

// Replaces the sample plan with `markdown`, through its Markdown, as the operator would.
async function write(page: Page, markdown: string): Promise<void> {
    const mode = page.getByRole('button', { name: 'Markdown', exact: true })
    await mode.click()
    await page.getByRole('textbox', { name: 'Plan as Markdown' }).fill(markdown)
    await mode.click()
}

test("the sample plan's Mermaid block is drawn as its diagram, its source under Source", async ({ page }) => {
    const doc = plan(page)
    const diagram = doc.getByRole('img', { name: /^A sequence diagram/u })
    await expect(diagram).toBeVisible()
    expect(await diagram.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(100)
    const source = doc.getByText('participant Page as web: reports page')
    await expect.poll(() => inSight(source)).toBe(false)

    const toggle = doc.getByRole('button', { name: 'Source' })
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-pressed', 'true')
    await expect.poll(() => inSight(source)).toBe(true)
    await toggle.click()
    await expect.poll(() => inSight(source)).toBe(false)

    // The block is still its Markdown, written back as it was read.
    await page.getByRole('button', { name: 'Show Markdown' }).click()
    await expect(page.getByLabel('Plan Markdown')).toContainText('```mermaid\nsequenceDiagram\n    participant Page')
})

test('the caret moved into a diagram shows its source, and an edit there draws it again', async ({ page }) => {
    const doc = plan(page)
    const diagram = doc.getByRole('img', { name: /^A sequence diagram/u })
    await expect(diagram).toBeVisible()
    const before = await diagram.getAttribute('src')
    const source = doc.getByText('participant Page as web: reports page')
    await expect.poll(() => inSight(source)).toBe(false)

    // From the start of the heading after it, back into the end of its code, as the keyboard goes.
    await doc.getByRole('heading', { name: 'Files' }).click()
    await page.keyboard.press('Home')
    await page.keyboard.press('ArrowLeft')
    await expect.poll(() => inSight(source)).toBe(true)
    await page.keyboard.type('\nPage->>Page: says it is done')
    await expect(diagram).not.toHaveAttribute('src', before ?? '')
    await expect(diagram).toBeVisible()

    // Out of it again, the diagram is all there is.
    await doc.getByRole('heading', { name: 'Files' }).click()
    await expect.poll(() => inSight(source)).toBe(false)
})

test('a diagram mermaid cannot read, or of a kind not drawn here, shows its source and why', async ({ page }) => {
    await write(page, '# Plan\n\n```mermaid\nflowchart LR\n  A -->\n```\n\n```mermaid\npie\n  "a": 1\n```\n')
    const doc = plan(page)
    await expect(doc.getByText(/^Not drawn: Parse error on line/u)).toBeVisible()
    await expect(
        doc.getByText('Not drawn: a pie diagram is not drawn here, only flowchart, sequenceDiagram'),
    ).toBeVisible()
    await expect(doc.getByText('A -->')).toBeVisible()
    await expect(doc.getByText('"a": 1')).toBeVisible()
    await expect(doc.getByRole('img')).toHaveCount(0)
})

test("what a diagram's labels write as HTML stays text, and its config cannot say otherwise", async ({ page }) => {
    const fetched: string[] = []
    page.on('request', (request) => {
        if (new URL(request.url()).pathname.endsWith('/pwned.png')) {
            fetched.push(request.url())
        }
    })
    await write(
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
