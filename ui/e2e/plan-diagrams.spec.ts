import { expect, test } from '@playwright/test'
import type { Locator } from '@playwright/test'

import { clickAtEnd, clickAtStart, plan, settled, signIn, writePlan } from './helpers.ts'

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

test("a table's code breaks where it must, so a wide table's columns are all in view", async ({ page }) => {
    // In the operator's window (PRODUCT.md), where the plan keeps its measure beside its comments.
    await page.setViewportSize({ width: 1720, height: 1300 })
    const row = [
        'api',
        '`api/reports/query/iterators/paged_rows.py`',
        'raise it when the connection drops mid-page',
        '`iter_rows(report_id: int, *, resume_from: Cursor | None = None) -> Iterator[Row]`',
        '`test_paged_rows.py`',
        'a dropped page resumes',
    ]
    await writePlan(
        page,
        `# Plan\n\n| Repository | File | Change | Signature | Test | Acceptance |\n${'| --- '.repeat(6)}|\n` +
            `| ${row.join(' | ')} |\n`,
    )
    const wrapper = plan(page).getByRole('table').locator('xpath=..')
    await expect(plan(page).getByRole('columnheader', { name: 'Acceptance' })).toBeVisible()
    const fits = await wrapper.evaluate((box) => box.scrollWidth <= box.clientWidth)
    expect(fits).toBe(true)
    await expect(wrapper).not.toHaveAttribute('data-more-end')
})

test('a table too wide for the plan scrolls, its far edge faded', async ({ page }) => {
    const heads = Array.from({ length: 14 }, (_, i) => `Criterion ${i + 1}`)
    await writePlan(
        page,
        `# Plan\n\n| ${heads.join(' | ')} |\n${'| --- '.repeat(14)}|\n| ${heads.map(() => 'unbroken').join(' | ')} |\n`,
    )
    const wrapper = plan(page).getByRole('table').locator('xpath=..')
    await expect(wrapper).toHaveAttribute('data-more-end')
    await expect(wrapper).not.toHaveAttribute('data-more-start')
    await wrapper.evaluate((box) => {
        box.scrollLeft = box.scrollWidth
    })
    await expect(wrapper).toHaveAttribute('data-more-start')
    await expect(wrapper).not.toHaveAttribute('data-more-end')
})
