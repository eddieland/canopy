import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

import { clickAtEnd, clickIn, plan, select, settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
    await page.goto('plan-editor')
    await settled(page)
})

// Clicks into the passage of thread `id`, `offset` characters in, as the operator would.
async function caretAt(page: Page, id: string, offset: number): Promise<void> {
    const point = await plan(page)
        .locator(`[data-thread="${id}"]`)
        .evaluate((element, at) => {
            const range = document.createRange()
            range.setStart(element.firstChild ?? element, at)
            const box = range.getBoundingClientRect()
            return { x: box.x, y: box.y + box.height / 2 }
        }, offset)
    await page.mouse.click(point.x, point.y)
}

// Pastes `text` into the plan as the browser would from a clipboard holding it as plain text alone.
async function paste(page: Page, text: string): Promise<void> {
    await plan(page).evaluate((root, value) => {
        const data = new DataTransfer()
        data.setData('text/plain', value)
        root.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
    }, text)
}

// How far apart, in pixels, the tops of two elements are.
async function topGap(a: Locator, b: Locator): Promise<number> {
    const [boxA, boxB] = await Promise.all([a.boundingBox(), b.boundingBox()])
    return Math.abs((boxA?.y ?? 0) - (boxB?.y ?? Infinity))
}

// What the changes since the plan before are marked with: words added and removed, and blocks and cells added whole.
const MARKS = 'ins, del, .plan-block-add, .plan-cell-add'

function comments(page: Page): Locator {
    return page.getByRole('article')
}

test('the sample plan opens with its comments on their passages, a rewritten one marked gone', async ({ page }) => {
    const doc = plan(page)
    await expect(doc.getByRole('heading', { level: 3 })).toHaveText('Export reports as CSV')
    await expect(doc.locator('table')).toBeVisible()
    await expect(doc.locator('[data-thread=sample-1]')).toHaveText("streams the report's rows as they are read")
    await expect(comments(page)).toHaveCount(3)
    await expect(comments(page).nth(2)).toContainText('passage gone')
    await expect(page.getByRole('button', { name: 'Show 1 resolved' })).toBeVisible()
})

test('selecting text and pressing Comment adds a thread on it, highlighted in the plan', async ({ page }) => {
    await select(page, "Excel's own format")
    await page.getByRole('toolbar', { name: 'Format' }).getByRole('button', { name: 'Comment' }).click()
    const form = page.getByRole('form', { name: 'Comment' })
    await form.getByRole('textbox').fill('Say why not: one customer asked.')
    await form.getByRole('button', { name: 'Comment' }).click()
    const thread = comments(page).filter({ hasText: 'one customer asked' })
    await expect(thread).toHaveAttribute('data-active', 'true')
    const id = await thread.getAttribute('data-thread')
    await expect(page.locator(`.plan-doc [data-thread="${id}"]`)).toHaveText("Excel's own format")
})

test('a label leads a comment with its instruction, and the operator’s words follow it', async ({ page }) => {
    await select(page, "Excel's own format")
    await page.keyboard.press('ControlOrMeta+Alt+m')
    const form = page.getByRole('form', { name: 'Comment' })
    await form.getByRole('group', { name: 'Labels' }).getByRole('button', { name: 'Verify this' }).click()
    await expect(form.getByRole('textbox')).toBeFocused()
    await page.keyboard.type('Name the customer.')
    await expect(form.getByRole('textbox')).toHaveValue(/^Verify this: .+\n\nName the customer\.$/su)
    await form.getByRole('button', { name: 'Comment', exact: true }).click()
    const thread = comments(page).filter({ hasText: 'Name the customer.' })
    await expect(thread).toContainText('Verify this: check the claim against the code')
})

test('a comment stays on its passage while the plan is edited above it', async ({ page }) => {
    const doc = plan(page)
    await clickAtEnd(doc.getByRole('heading', { level: 3 }))
    await page.keyboard.type(', streamed')
    await expect(doc.getByRole('heading', { level: 3 })).toHaveText('Export reports as CSV, streamed')
    await expect(doc.locator('[data-thread=sample-1]')).toHaveText("streams the report's rows as they are read")
    await page.getByRole('button', { name: 'Show Markdown' }).click()
    await expect(page.getByLabel('Plan Markdown')).toContainText('# Export reports as CSV, streamed')
})

test('Markdown swaps the plan for its text, and an edit there comes back with its comments', async ({ page }) => {
    const mode = page.getByRole('button', { name: 'Markdown', exact: true })
    await mode.click()
    await expect(mode).toHaveAttribute('aria-pressed', 'true')
    const source = page.getByRole('textbox', { name: 'Plan as Markdown' })
    await expect(source).toHaveValue(/^# Export reports as CSV\n\n## What changes\n/u)
    await expect(plan(page)).toBeHidden()
    await expect(page.getByRole('toolbar', { name: 'Format' })).toBeHidden()
    await source.fill((await source.inputValue()).replace('# Export reports as CSV', '# Export reports as CSV, raw'))
    // What the editor says of the plan follows the text as it is typed.
    await page.getByRole('button', { name: 'Show Markdown' }).click()
    await expect(page.getByLabel('Plan Markdown')).toContainText('# Export reports as CSV, raw')
    await mode.click()
    await expect(source).toBeHidden()
    const doc = plan(page)
    await expect(doc.getByRole('heading', { level: 3 })).toHaveText('Export reports as CSV, raw')
    await expect(doc.locator('[data-thread=sample-1]')).toHaveText("streams the report's rows as they are read")
    await expect(comments(page)).toHaveCount(3)
    // The whole edit is one step back.
    await page.getByRole('toolbar', { name: 'Format' }).getByRole('button', { name: 'Undo' }).click()
    await expect(doc.getByRole('heading', { level: 3 })).toHaveText('Export reports as CSV')
})

test('a wrapped line reads as one paragraph, and an edit undone leaves the Markdown as it was', async ({ page }) => {
    await page.getByRole('button', { name: 'Show Markdown' }).click()
    const markdown = page.getByLabel('Plan Markdown')
    const before = await markdown.textContent()
    // The sample's first paragraph wraps after `export.csv`,. A matcher collapses whitespace, so these compare exactly.
    expect(before).toContain('export.csv`,\nwhich streams')
    expect(await plan(page).locator('p').first().textContent()).toContain('export.csv, which streams')
    await caretAt(page, 'sample-1', 8)
    await page.keyboard.type('x')
    await page.keyboard.press('Backspace')
    await expect.poll(() => markdown.textContent()).toBe(before)
})

test('a word typed inside a commented passage on a wrapped line stays in its comment', async ({ page }) => {
    await caretAt(page, 'sample-1', "streams the report's ".length)
    await page.keyboard.type('many ')
    const passage = plan(page).locator('[data-thread=sample-1]')
    await expect(passage).toHaveText("streams the report's many rows as they are read")
})

test('the toolbar formats the selection and says what is in force', async ({ page }) => {
    await select(page, 'Scheduling exports.')
    const bold = page.getByRole('toolbar', { name: 'Format' }).getByRole('button', { name: 'Bold' })
    await bold.click()
    await expect(bold).toHaveAttribute('aria-pressed', 'true')
    await page.getByRole('button', { name: 'Show Markdown' }).click()
    await expect(page.getByLabel('Plan Markdown')).toContainText('- **Scheduling exports.**')
})

test('each toolbar control names a shortcut on hover, and that shortcut does what the control does', async ({
    page,
}) => {
    const toolbar = page.getByRole('toolbar', { name: 'Format' })
    await expect(toolbar.getByRole('button', { name: 'Bold' })).toHaveAttribute('title', /^Bold \((Ctrl\+B|⌘B)\)$/u)
    // The paragraph's style is a choice of one, in a menu that names each style's keys: each picks its style, the last
    // going back to text.
    const styles = ['Heading 1', 'Heading 2', 'Heading 3', 'Heading 4', 'Text']
    const menu = toolbar.getByRole('button', { name: /^Text style/u })
    await menu.click()
    const styleKeys = await Promise.all(
        styles.map((name) => page.getByRole('menuitemradio', { name, exact: true }).getAttribute('aria-keyshortcuts')),
    )
    await page.keyboard.press('Escape')
    await select(page, 'method')
    for (const [i, name] of styles.entries()) {
        await page.keyboard.press(styleKeys[i] ?? '')
        await expect(menu).toHaveAccessibleName(`Text style: ${name}`)
    }
    // A mark or a block is on or off: its shortcut turns it on, and again off.
    for (const name of ['Bold', 'Italic', 'Strikethrough', 'Code', 'Bulleted list', 'Numbered list', 'Task list']) {
        const control = toolbar.getByRole('button', { name, exact: true })
        const keys = (await control.getAttribute('aria-keyshortcuts')) ?? ''
        await page.keyboard.press(keys)
        await expect(control, name).toHaveAttribute('aria-pressed', 'true')
        await page.keyboard.press(keys)
        await expect(control, name).toHaveAttribute('aria-pressed', 'false')
    }
    for (const name of ['Quote', 'Code block']) {
        const control = toolbar.getByRole('button', { name, exact: true })
        await page.keyboard.press((await control.getAttribute('aria-keyshortcuts')) ?? '')
        await expect(control, name).toHaveAttribute('aria-pressed', 'true')
        await page.keyboard.press('ControlOrMeta+z')
        await expect(control, name).toHaveAttribute('aria-pressed', 'false')
    }
})

test('the style menu shows each style as the plan sets it, and leaves the cursor in the plan', async ({ page }) => {
    await select(page, 'Out of scope')
    const menu = page.getByRole('toolbar', { name: 'Format' }).getByRole('button', { name: /^Text style/u })
    await expect(menu).toHaveAccessibleName('Text style: Heading 2')
    await menu.click()
    await expect(page.getByRole('menuitemradio', { name: 'Heading 2', exact: true })).toBeChecked()
    await page.getByRole('menuitemradio', { name: 'Heading 4', exact: true }).click()
    await expect(menu).toHaveAccessibleName('Text style: Heading 4')
    await expect(plan(page)).toBeFocused()
    await expect(plan(page).getByRole('heading', { level: 6, name: 'Out of scope' })).toBeVisible()
    await page.getByRole('button', { name: 'Show Markdown' }).click()
    await expect(page.getByLabel('Plan Markdown')).toContainText('#### Out of scope')
})

test('the table menu inserts a table where none is, and only there', async ({ page }) => {
    await clickAtEnd(plan(page).locator('blockquote p'))
    await page.keyboard.press('Enter')
    await page.keyboard.press('Enter')
    await page.getByRole('toolbar', { name: 'Format' }).getByRole('button', { name: 'Table' }).click()
    await expect(page.getByRole('menuitem', { name: 'Delete row' })).toBeDisabled()
    await page.getByRole('menuitem', { name: 'Insert table' }).click()
    await expect(plan(page).locator('table')).toHaveCount(2)
    await expect(plan(page)).toBeFocused()
    await page.keyboard.type('Step')
    await page.getByRole('button', { name: 'Show Markdown' }).click()
    await expect(page.getByLabel('Plan Markdown')).toContainText('| Step')
})

test('in a table, the table menu adds and deletes its rows and columns, and the table', async ({ page }) => {
    const table = plan(page).locator('table')
    const pick = async (name: string) => {
        await page.getByRole('toolbar', { name: 'Format' }).getByRole('button', { name: 'Table' }).click()
        await page.getByRole('menuitem', { name }).click()
    }
    await table.locator('td', { hasText: 'the button' }).click()
    await page.getByRole('toolbar', { name: 'Format' }).getByRole('button', { name: 'Table' }).click()
    await expect(page.getByRole('menuitem', { name: 'Insert table' })).toBeDisabled()
    await page.keyboard.press('Escape')
    await table.locator('td', { hasText: 'the button' }).click()
    await pick('Add row below')
    await expect(table.locator('tr')).toHaveCount(5)
    await pick('Delete row')
    await expect(table.locator('tr')).toHaveCount(4)
    await pick('Add column right')
    await expect(table.locator('tr').first().locator('th')).toHaveCount(4)
    await pick('Delete column')
    await expect(table.locator('tr').first().locator('th')).toHaveCount(3)
    await pick('Delete table')
    await expect(table).toHaveCount(0)
})

test('an empty plan says what goes in it', async ({ page }) => {
    await plan(page).click()
    await page.keyboard.press('ControlOrMeta+a')
    await page.keyboard.press('Backspace')
    await expect(plan(page).locator('p').first()).toHaveAttribute(
        'data-placeholder',
        'Write the plan here, or paste its Markdown.',
    )
})

test('the toolbar stays at the top of the page while the plan scrolls under it', async ({ page }) => {
    const toolbar = page.getByRole('toolbar', { name: 'Format' })
    await select(page, 'template cache')
    await plan(page).locator('blockquote').scrollIntoViewIfNeeded()
    await page.locator('.page-scroll').evaluate((scroller) => scroller.scrollBy(0, 400))
    const top = await page.locator('.page-scroll').evaluate((scroller) => scroller.getBoundingClientRect().top)
    await expect.poll(async () => (await toolbar.boundingBox())?.y).toBeGreaterThanOrEqual(top)
    await expect(toolbar).toBeInViewport()
    await toolbar.getByRole('button', { name: 'Bold' }).click()
    await page.getByRole('button', { name: 'Show Markdown' }).click()
    await expect(page.getByLabel('Plan Markdown')).toContainText('a **template cache**')
})

test("the outline lists the plan's headings and goes to the one chosen, under the toolbar, the cursor in it", async ({
    page,
}) => {
    const toolbar = page.getByRole('toolbar', { name: 'Format' })
    await page.getByRole('button', { name: 'Outline' }).click()
    await expect(page.getByRole('menuitem')).toHaveText([
        'Export reports as CSV',
        'What changes',
        'Files',
        'Tests',
        'Out of scope',
        'Risks',
    ])
    await page.getByRole('menuitem', { name: 'Tests' }).click()
    const heading = plan(page).getByRole('heading', { name: 'Tests' })
    await expect(heading).toBeInViewport()
    const below = async () => {
        const [bar, top] = await Promise.all([toolbar.boundingBox(), heading.boundingBox()])
        return (top?.y ?? 0) - ((bar?.y ?? 0) + (bar?.height ?? 0))
    }
    await expect.poll(below).toBeGreaterThanOrEqual(0)
    await expect(plan(page)).toBeFocused()
    await expect(toolbar.getByRole('button', { name: /^Text style/u })).toHaveAccessibleName('Text style: Heading 2')
})

test('the outline marks the section being read as it opens', async ({ page }) => {
    const outline = page.getByRole('button', { name: 'Outline' })
    await outline.click()
    await expect(page.getByRole('menuitem', { name: 'Export reports as CSV' })).toHaveAttribute(
        'aria-current',
        'location',
    )
    await page.getByRole('menuitem', { name: 'Files' }).click()
    await outline.click()
    await expect(page.getByRole('menuitem', { name: 'Files' })).toHaveAttribute('aria-current', 'location')
    await expect(page.locator('[role=menuitem][aria-current]')).toHaveCount(1)
})

test('each comment sits beside its passage, and moves with it as the plan is edited above', async ({ page }) => {
    const card = comments(page).filter({ hasText: 'proxy in front' })
    const passage = plan(page).locator('[data-thread=sample-1]')
    await expect.poll(() => topGap(card, passage)).toBeLessThanOrEqual(1)
    await clickAtEnd(plan(page).getByRole('heading', { level: 3 }))
    await page.keyboard.press('Enter')
    await page.keyboard.type('A paragraph that moves every passage under it down.')
    await expect.poll(() => topGap(card, passage)).toBeLessThanOrEqual(1)
})

test('typing in the middle of a comment being written edits it in place', async ({ page }) => {
    await select(page, "Excel's own format")
    await page.keyboard.press('ControlOrMeta+Alt+m')
    const field = page.getByRole('form', { name: 'Comment' }).getByRole('textbox')
    await expect(field).toBeFocused()
    await page.keyboard.type('abc')
    await page.keyboard.press('ArrowLeft')
    await page.keyboard.press('ArrowLeft')
    await page.keyboard.type('X')
    await expect(field).toHaveValue('aXbc')
})

test('a comment opens beside its passage, without the page moving', async ({ page }) => {
    // As the operator would find it: in the middle of the window.
    await plan(page)
        .getByText("Excel's own format")
        .evaluate((element) => element.scrollIntoView({ block: 'center' }))
    await select(page, "Excel's own format")
    const scroller = page.locator('.page-scroll')
    const before = await scroller.evaluate((element) => element.scrollTop)
    await page.keyboard.press('ControlOrMeta+Alt+m')
    const form = page.getByRole('form', { name: 'Comment' })
    await expect(form.getByRole('textbox')).toBeFocused()
    expect(await scroller.evaluate((element) => element.scrollTop)).toBe(before)
    const draft = page.locator('[data-align=draft]')
    const passage = plan(page).locator('.plan-comment-active').filter({ hasText: "Excel's own format" })
    await expect.poll(() => topGap(draft, passage)).toBeLessThanOrEqual(1)
})

// Where the page is too narrow for the comments beside the plan, they sit under it, as a list.
test.describe('with the comments under the plan', () => {
    test.use({ viewport: { width: 1000, height: 800 } })

    test('the comments are a list under the plan, none placed at its passage', async ({ page }) => {
        const doc = await plan(page).boundingBox()
        const first = await comments(page).first().boundingBox()
        expect(first?.y).toBeGreaterThan((doc?.y ?? 0) + (doc?.height ?? 0))
        await expect(page.locator('.plan-margin[data-aligned]')).toHaveCount(0)
    })

    test('a comment being written floats under its passage, and the page stays where it is', async ({ page }) => {
        await select(page, 'iter_rows()')
        const scrolled = await page.evaluate(() => globalThis.scrollY)
        await page.keyboard.press('ControlOrMeta+Alt+m')
        const float = page.getByTestId('plan-float')
        const form = float.getByRole('form', { name: 'Comment' })
        await expect(form.getByRole('textbox')).toBeFocused()
        const passage = await plan(page).getByText('iter_rows()').first().boundingBox()
        const box = await float.boundingBox()
        expect(box?.y).toBeGreaterThan((passage?.y ?? 0) + (passage?.height ?? 0))
        expect(box?.y).toBeLessThan((passage?.y ?? 0) + (passage?.height ?? 0) + 24)
        expect(await page.evaluate(() => globalThis.scrollY)).toBe(scrolled)
        await page.keyboard.type('Why not rows()?')
        await form.getByRole('button', { name: 'Comment' }).click()
        await expect(float).toBeHidden()
        await expect(comments(page).filter({ hasText: 'Why not rows()?' })).toHaveCount(1)
        await expect(plan(page)).toBeFocused()
    })

    test('a passage clicked opens its thread over the plan, not down in the list, and Escape closes it', async ({
        page,
    }) => {
        await plan(page).locator('[data-thread=sample-2]').click()
        const float = page.getByTestId('plan-float')
        await expect(float.getByRole('article')).toContainText('name the ticket')
        await expect(comments(page).filter({ hasText: 'name the ticket' })).toHaveCount(1)
        await page.keyboard.press('Escape')
        await expect(float).toBeHidden()
        await expect(comments(page).filter({ hasText: 'name the ticket' })).toHaveCount(1)

        // The caret back in the passage opens its thread in the list: only a click floats it.
        await page.keyboard.press('ArrowRight')
        await expect(comments(page).filter({ hasText: 'name the ticket' })).toHaveAttribute('data-active', 'true')
        await expect(float).toBeHidden()
    })

    test('a comment shows its passage in the plan, clear of the toolbar', async ({ page }) => {
        const card = comments(page).filter({ hasText: 'proxy in front' })
        await card.scrollIntoViewIfNeeded()
        const passage = plan(page).locator('[data-thread=sample-1]')
        await expect(passage).not.toBeInViewport()
        await card.getByRole('button', { name: "streams the report's rows" }).click()
        await expect(passage).toBeInViewport()
        const toolbar = await page.getByRole('toolbar', { name: 'Format' }).boundingBox()
        expect((await passage.boundingBox())?.y).toBeGreaterThanOrEqual((toolbar?.y ?? 0) + (toolbar?.height ?? 0))
    })
})

test.describe('on a wide monitor', () => {
    test.use({ viewport: { width: 1700, height: 900 } })

    test("the comments stay against the plan's text, the room left over after them", async ({ page }) => {
        const text = await plan(page).boundingBox()
        const column = await page.locator('.plan-margin').boundingBox()
        const gap = (column?.x ?? Infinity) - ((text?.x ?? 0) + (text?.width ?? 0))
        // The panel's padding and the grid's gap: 1.5rem and 1.5rem, and no more.
        expect(gap).toBeLessThanOrEqual(56)
    })
})

// The narrowest window the UI holds up in (e2e/narrow.spec.ts): the toolbar's header, its label's line and the
// toolbar's under it, must still fit there within the 80px the editor keeps clear under it (TOOLBAR_CLEARANCE in
// src/components/plan-editor.tsx).
test.describe('in a narrow window', () => {
    test.use({ viewport: { width: 820, height: 900 } })

    test('the stuck toolbar fits in the space the editor keeps clear, and covers no passage it shows', async ({
        page,
    }) => {
        const header = page.getByRole('toolbar', { name: 'Format' }).locator('xpath=..')
        const card = comments(page).filter({ hasText: 'proxy in front' })
        await card.scrollIntoViewIfNeeded()
        const stuck = await header.boundingBox()
        expect(stuck?.height).toBeLessThan(80)
        const passage = plan(page).locator('[data-thread=sample-1]')
        await card.getByRole('button', { name: "streams the report's rows" }).click()
        await expect(passage).toBeInViewport()
        const box = await header.boundingBox()
        expect((await passage.boundingBox())?.y).toBeGreaterThanOrEqual((box?.y ?? 0) + (box?.height ?? 0))
    })
})

test('Markdown pasted into the plan becomes the headings, lists, and marks it writes', async ({ page }) => {
    await clickAtEnd(plan(page).locator('blockquote p'))
    await page.keyboard.press('Enter')
    await page.keyboard.press('Enter')
    await paste(page, '## Rollout\n\n- **ship** behind a flag\n- remove the flag')
    await expect(plan(page).getByRole('heading', { level: 4, name: 'Rollout' })).toBeVisible()
    await expect(plan(page).locator('li').filter({ hasText: 'remove the flag' })).toBeVisible()
    await expect(plan(page).locator('strong').filter({ hasText: 'ship' })).toBeVisible()
    await page.getByRole('button', { name: 'Show Markdown' }).click()
    await expect(page.getByLabel('Plan Markdown')).toContainText('## Rollout')
    await expect(page.getByLabel('Plan Markdown')).toContainText('- **ship** behind a flag')
})

test('inline Markdown pasted into a sentence stays in it, and prose or a Shift paste stays as written', async ({
    page,
}) => {
    await select(page, 'Scheduling exports.')
    await paste(page, 'Scheduling `cron` exports.')
    await expect(plan(page).locator('li code').filter({ hasText: 'cron' })).toBeVisible()
    await select(page, "Excel's own format")
    await paste(page, 'Spreadsheet formats')
    await expect(plan(page).getByText('Spreadsheet formats, which the ticket')).toBeVisible()
    await select(page, 'Spreadsheet formats')
    // Ctrl+Shift+V, as the browser pastes plain text: Shift held in the plan.
    await plan(page).focus()
    await page.keyboard.down('Shift')
    await paste(page, '**Spreadsheets** and `.ods`')
    await page.keyboard.up('Shift')
    await expect(plan(page).getByText('**Spreadsheets** and `.ods`, which the ticket')).toBeVisible()
})

test('Markdown pasted into a code block stays code, as its characters', async ({ page }) => {
    await clickAtEnd(plan(page).locator('blockquote p'))
    await page.keyboard.press('Enter')
    await page.keyboard.press('Enter')
    await page.getByRole('button', { name: 'Code block', exact: true }).click()
    await paste(page, '- name: web\n- name: api\n# both deploy')
    // The new block, after the sample's diagram.
    await expect(plan(page).locator('pre').last()).toContainText('- name: web')
    await expect(plan(page).locator('li').filter({ hasText: 'name: web' })).toHaveCount(0)
    await expect(plan(page).getByRole('heading', { name: 'both deploy' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Show Markdown' }).click()
    await expect(page.getByLabel('Plan Markdown')).toContainText('```\n- name: web\n- name: api\n# both deploy\n```')
})

test.describe('copying out of the plan', () => {
    test.use({ permissions: ['clipboard-read', 'clipboard-write'] })

    test('lines of a list copy as the Markdown that writes them, words in a line as the words', async ({ page }) => {
        // From the start of the first item to the end of the second, as a drag over both would select.
        await plan(page).evaluate((root) => {
            const items = [...root.querySelectorAll('li')].filter((item) => item.closest('ul[data-type]') === null)
            const first = items.find((item) => item.textContent.startsWith('Excel'))
            const second = items.find((item) => item.textContent.startsWith('Scheduling'))
            const range = document.createRange()
            range.setStart(first?.querySelector('p')?.firstChild ?? root, 0)
            const last = second?.querySelector('p')
            range.setEndAfter(last?.lastChild ?? root)
            root.focus()
            globalThis.getSelection()?.removeAllRanges()
            globalThis.getSelection()?.addRange(range)
        })
        await page.keyboard.press('ControlOrMeta+c')
        expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
            "- Excel's own format, which the ticket does not ask for.\n- Scheduling exports.",
        )
        await select(page, 'iter_rows()')
        await page.keyboard.press('ControlOrMeta+c')
        expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('iter_rows()')
    })
})

test('a card carries resolve and delete in its header, and reply only while it is the open one', async ({ page }) => {
    const thread = comments(page).filter({ hasText: 'name the ticket' })
    await expect(thread.getByRole('button', { name: 'resolve', exact: true })).toBeVisible()
    await expect(thread.getByRole('button', { name: 'delete', exact: true })).toBeVisible()
    await expect(thread.getByRole('button', { name: 'reply', exact: true })).toHaveCount(0)
    await thread.getByText('Keep this out').click()
    await expect(thread.getByRole('button', { name: 'reply', exact: true })).toBeVisible()
    // One whose passage is gone cannot be opened from the plan, so it keeps its reply.
    const lost = comments(page).filter({ hasText: 'passage gone' })
    await expect(lost.getByRole('button', { name: 'reply', exact: true })).toBeVisible()
})

test('comments whose passages are gone are resolved together, once there is more than one', async ({ page }) => {
    await expect(page.getByRole('button', { name: /^resolve all/u })).toHaveCount(0)
    await select(page, 'Scheduling exports.')
    await page.keyboard.press('Backspace')
    await expect(comments(page).filter({ hasText: 'passage gone' })).toHaveCount(2)
    await page.getByRole('button', { name: 'resolve all 2' }).click()
    await expect(comments(page)).toHaveCount(1)
    await expect(page.getByRole('button', { name: 'Show 3 resolved' })).toBeVisible()
})

test('resolving a thread folds it away and takes its highlight off the plan', async ({ page }) => {
    const thread = comments(page).filter({ hasText: 'name the ticket' })
    await thread.getByRole('button', { name: 'resolve', exact: true }).click()
    await expect(comments(page)).toHaveCount(2)
    await expect(page.locator('.plan-doc [data-thread=sample-2]')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Show 2 resolved' })).toBeVisible()
})

test('deleting a comment asks first, in its place, and Keep or Escape keeps it', async ({ page }) => {
    const thread = comments(page).filter({ hasText: 'proxy in front' })
    await thread.getByRole('button', { name: 'delete', exact: true }).click()
    const confirm = thread.getByRole('group', { name: 'Delete this comment and its replies?' })
    await expect(confirm.getByRole('button', { name: 'Keep' })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(confirm).toBeHidden()
    // Kept, the focus goes back to the delete that asked, each time.
    await expect(thread.getByRole('button', { name: 'delete', exact: true })).toBeFocused()
    await page.keyboard.press('Enter')
    await confirm.getByRole('button', { name: 'Keep' }).click()
    await expect(thread.getByRole('button', { name: 'delete', exact: true })).toBeFocused()
    await thread.getByRole('button', { name: 'delete', exact: true }).click()
    await confirm.getByRole('button', { name: 'Delete' }).click()
    await expect(thread).toHaveCount(0)
    await expect(plan(page).locator('[data-thread=sample-1]')).toHaveCount(0)
})

test('a comment and a reply are edited in place, and the planner reads what they say now', async ({ page }) => {
    // By its id: while its comment is in the form, the card's text no longer holds it.
    const thread = page.locator('article[data-thread=sample-1]')
    await thread.getByRole('button', { name: 'Edit comment' }).click()
    const comment = thread.getByRole('form', { name: 'Edit comment' }).getByRole('textbox')
    await expect(comment).toBeFocused()
    await expect(comment).toHaveValue(
        'Does the proxy in front of web buffer responses? If it does, streaming buys nothing.',
    )
    await comment.fill('Does the proxy buffer responses?')
    await thread.getByRole('button', { name: 'Save' }).click()
    await expect(thread).toContainText('Does the proxy buffer responses?')
    await thread.getByRole('button', { name: 'Edit reply' }).click()
    const reply = thread.getByRole('form', { name: 'Edit reply' }).getByRole('textbox')
    await reply.fill('It buffers up to 2 MB.')
    await thread.getByRole('button', { name: 'Cancel' }).click()
    await expect(thread).toContainText('It buffers up to 1 MB.')
    await thread.getByRole('button', { name: 'Edit reply' }).click()
    await reply.fill('It buffers up to 2 MB.')
    await thread.getByRole('button', { name: 'Save' }).click()
    await expect(thread).toContainText('It buffers up to 2 MB.')
    await page.getByRole('form', { name: 'Ask for changes' }).getByRole('button', { name: 'Ask for changes' }).click()
    await expect(page.getByLabel('Change request')).toContainText('Does the proxy buffer responses?')
    await expect(page.getByLabel('Change request')).toContainText('Reply: It buffers up to 2 MB.')
})

test('Ask for changes stays at the bottom of the page while the plan is read, and rests under it at its end', async ({
    page,
}) => {
    const ask = page.getByRole('form', { name: 'Ask for changes' }).getByRole('button', { name: 'Ask for changes' })
    await expect(plan(page).locator('blockquote')).not.toBeInViewport()
    await expect(ask).toBeInViewport()
    await plan(page).locator('blockquote').scrollIntoViewIfNeeded()
    await page.mouse.wheel(0, 2000)
    const bar = await page.getByTestId('plan-bar').boundingBox()
    const doc = await plan(page).boundingBox()
    expect(bar?.y).toBeGreaterThan((doc?.y ?? 0) + (doc?.height ?? 0))
})

test('Changes marks what the plan changed since the one it replaces, and off, marks nothing', async ({ page }) => {
    const changes = page.getByRole('button', { name: 'Changes since plan 1' })
    await expect(changes).toHaveAttribute('aria-pressed', 'false')
    await expect(plan(page).locator(MARKS)).toHaveCount(0)
    await changes.click()
    await expect(changes).toHaveAttribute('aria-pressed', 'true')
    await expect(plan(page).locator('ins').filter({ hasText: 'three lines' })).toBeVisible()
    await expect(plan(page).locator('del').filter({ hasText: 'a row per line' })).toBeVisible()
    // A paragraph added whole is marked as one block, not as its words.
    await expect(plan(page).locator('.plan-block-add').filter({ hasText: 'Scheduling exports' })).toBeVisible()
    await expect(plan(page).locator('ins').filter({ hasText: 'Scheduling exports' })).toHaveCount(0)
    // A section that moved says so at its heading, and one dropped is one line where it was, its words folded in it.
    await expect(plan(page).getByRole('heading', { name: 'Risks' })).toContainText('moved')
    const dropped = plan(page).getByText('Section removed: Rollout')
    await expect(plan(page).getByText('Behind a flag, on for one team first.')).toBeHidden()
    await dropped.click()
    await expect(plan(page).getByText('Behind a flag, on for one team first.')).toBeVisible()
    // What it marks is no part of the plan: its Markdown is as it was.
    await page.getByRole('button', { name: 'Show Markdown' }).click()
    await expect(page.getByLabel('Plan Markdown')).not.toContainText('a row per line')
    await changes.click()
    await expect(plan(page).locator(MARKS)).toHaveCount(0)
})

test('the changes are counted, and Next and Previous step the cursor to each, round to the other end', async ({
    page,
}) => {
    await page.getByRole('button', { name: 'Changes since plan 1' }).click()
    await expect(page.getByText(/^\d+ changes$/u)).toBeVisible()
    // From the top, the one before is the last.
    await page.getByRole('button', { name: 'Previous change' }).click()
    await expect(plan(page)).toBeFocused()
    await expect(plan(page).locator(MARKS).last()).toBeInViewport()
    // And the one after the last is the first.
    await page.getByRole('button', { name: 'Next change' }).click()
    await expect(plan(page).locator(MARKS).first()).toBeInViewport()
})

test('Ask for changes sends the open comments, each on its passage, with the note', async ({ page }) => {
    const thread = comments(page).filter({ hasText: 'proxy in front' })
    await thread.getByText('Does the proxy').click()
    await thread.getByRole('button', { name: 'reply', exact: true }).click()
    const reply = page.getByRole('form', { name: 'Reply' })
    await reply.getByRole('textbox').fill('And a test that reads the first row before the last is written.')
    await reply.getByRole('button', { name: 'Reply' }).click()
    const ask = page.getByRole('form', { name: 'Ask for changes' })
    await ask.getByRole('textbox').fill('Keep it to one PR per repository.')
    await ask.getByRole('button', { name: 'Ask for changes' }).click()
    const request = page.getByLabel('Change request')
    await expect(request).toContainText('1. On "streams the report\'s rows as they are read":')
    await expect(request).toContainText('Reply: And a test that reads the first row')
    await expect(request).toContainText('(no longer in the plan)')
    await expect(request).not.toContainText('RFC 4180')
    await expect(request).toContainText('On the whole plan:\nKeep it to one PR per repository.')
    await expect(request).not.toContainText('I edited the plan myself')
})

test('a plan edited before Ask for changes says so, so the planner keeps the edits', async ({ page }) => {
    await select(page, 'Scheduling exports.')
    await page.keyboard.type('Scheduling exports, for now.')
    await page.getByRole('form', { name: 'Ask for changes' }).getByRole('button', { name: 'Ask for changes' }).click()
    await expect(page.getByLabel('Change request')).toContainText(
        'I edited the plan myself before asking: keep my edits, unless a comment here asks otherwise.',
    )
})

test('a plan edited and the edit undone says nothing of it', async ({ page }) => {
    await select(page, 'Scheduling exports.')
    await page.keyboard.type('Scheduling exports, for now.')
    await page.keyboard.press('ControlOrMeta+z')
    await expect(plan(page)).toContainText('Scheduling exports.')
    await page.getByRole('form', { name: 'Ask for changes' }).getByRole('button', { name: 'Ask for changes' }).click()
    await expect(page.getByLabel('Change request')).not.toContainText('I edited the plan myself')
})

test('clicking a commented passage opens its thread and puts the cursor there', async ({ page }) => {
    await plan(page).locator('[data-thread=sample-2]').click()
    await expect(comments(page).filter({ hasText: 'name the ticket' })).toHaveAttribute('data-active', 'true')
    await expect(plan(page).locator('[data-thread=sample-2]')).toHaveClass(/plan-comment-active/u)
    // The paragraph's style shows the cursor moved from the heading it opened in.
    const menu = page.getByRole('toolbar', { name: 'Format' }).getByRole('button', { name: /^Text style/u })
    await expect(menu).toHaveAccessibleName('Text style: Text')
})

test('the cursor moved into a commented passage by the keyboard opens its thread, and out of it closes it', async ({
    page,
}) => {
    const card = comments(page).filter({ hasText: 'name the ticket' })
    await clickIn(plan(page).locator('li').filter({ hasText: "Excel's own format" }))
    await expect(card).toHaveAttribute('data-active', 'false')
    await page.keyboard.press('ArrowDown')
    await expect(card).toHaveAttribute('data-active', 'true')
    await expect(plan(page).locator('[data-thread=sample-2]')).toHaveClass(/plan-comment-active/u)
    await page.keyboard.press('ArrowDown')
    await expect(card).toHaveAttribute('data-active', 'false')
})

test("a click anywhere on a thread's card opens it, and the plan stays where it is", async ({ page }) => {
    const card = comments(page).filter({ hasText: 'name the ticket' })
    const scrolled = await page.evaluate(() => globalThis.scrollY)
    await card.getByText('Keep this out').click()
    await expect(card).toHaveAttribute('data-active', 'true')
    await expect(plan(page).locator('[data-thread=sample-2]')).toHaveClass(/plan-comment-active/u)
    expect(await page.evaluate(() => globalThis.scrollY)).toBe(scrolled)
})

test('a click elsewhere in the plan, or Escape, closes the open thread', async ({ page }) => {
    const passage = plan(page).locator('[data-thread=sample-2]')
    const thread = comments(page).filter({ hasText: 'name the ticket' })
    await passage.click()
    await expect(thread).toHaveAttribute('data-active', 'true')
    await plan(page).getByRole('heading', { level: 3 }).click()
    await expect(thread).toHaveAttribute('data-active', 'false')
    await expect(plan(page).locator('.plan-comment-active')).toHaveCount(0)
    await passage.click()
    await expect(thread).toHaveAttribute('data-active', 'true')
    await page.keyboard.press('Escape')
    await expect(thread).toHaveAttribute('data-active', 'false')
    await expect(plan(page).locator('.plan-comment-active')).toHaveCount(0)
})

test('commenting again with nothing written moves the comment, and typing goes into it', async ({ page }) => {
    await select(page, 'iter_rows()')
    await page.keyboard.press('ControlOrMeta+Alt+m')
    await select(page, 'Export CSV')
    await page.keyboard.press('ControlOrMeta+Alt+m')
    const form = page.getByRole('form', { name: 'Comment' })
    await expect(form.getByRole('textbox')).toBeFocused()
    await page.keyboard.type('Name the button as the page shows it.')
    await expect(form.getByRole('textbox')).toHaveValue('Name the button as the page shows it.')
    await expect(plan(page).getByText('Export CSV')).toBeVisible()
    await form.getByRole('button', { name: 'Comment' }).click()
    const thread = comments(page).filter({ hasText: 'Name the button' })
    const id = await thread.getAttribute('data-thread')
    await expect(page.locator(`.plan-doc [data-thread="${id}"]`)).toHaveText('Export CSV')
})

test('commenting again on a comment half written keeps it on its passage, with its words', async ({ page }) => {
    await select(page, 'iter_rows()')
    await page.keyboard.press('ControlOrMeta+Alt+m')
    await page.keyboard.type('Why not rows()?')
    await select(page, 'Export CSV')
    await page.keyboard.press('ControlOrMeta+Alt+m')
    const form = page.getByRole('form', { name: 'Comment' })
    await expect(form.getByRole('textbox')).toBeFocused()
    await expect(form.getByRole('textbox')).toHaveValue('Why not rows()?')
    await page.keyboard.type(' It reads them all.')
    await expect(plan(page).getByText('Export CSV')).toBeVisible()
    await form.getByRole('button', { name: 'Comment' }).click()
    const thread = comments(page).filter({ hasText: 'Why not rows()? It reads them all.' })
    const id = await thread.getAttribute('data-thread')
    await expect(page.locator(`.plan-doc [data-thread="${id}"]`)).toHaveText('iter_rows()')
})

test('Escape puts a half-written comment aside with its words, and the cursor goes back to the plan', async ({
    page,
}) => {
    await select(page, 'iter_rows()')
    await page.keyboard.press('ControlOrMeta+Alt+m')
    await page.keyboard.type('Why not rows()?')
    await page.keyboard.press('Escape')
    const form = page.getByRole('form', { name: 'Comment' })
    await expect(plan(page)).toBeFocused()
    await expect(form.getByRole('textbox')).toHaveValue('Why not rows()?')
    await form.getByRole('button', { name: 'Cancel' }).click()
    await expect(form).toBeHidden()
    await expect(plan(page)).toBeFocused()
})

test('a reply half written is kept on Escape too, and an edit with nothing changed closes on it', async ({ page }) => {
    const thread = comments(page).filter({ hasText: 'proxy in front' })
    await thread.getByText('Does the proxy').click()
    await thread.getByRole('button', { name: 'reply', exact: true }).click()
    await page.keyboard.type('Ask ops.')
    await page.keyboard.press('Escape')
    await expect(plan(page)).toBeFocused()
    await expect(thread.getByRole('form', { name: 'Reply' }).getByRole('textbox')).toHaveValue('Ask ops.')
    const other = comments(page).filter({ hasText: 'name the ticket' })
    await other.getByRole('button', { name: 'Edit comment' }).click()
    await page.keyboard.press('Escape')
    await expect(other.getByRole('form', { name: 'Edit comment' })).toBeHidden()
    await expect(plan(page)).toBeFocused()
})

test('once a comment is sent or resolved, the cursor is back in the plan after its passage', async ({ page }) => {
    await select(page, "Excel's own format")
    await page.keyboard.press('ControlOrMeta+Alt+m')
    await page.keyboard.type('Say why not.')
    await page.getByRole('form', { name: 'Comment' }).getByRole('button', { name: 'Comment' }).click()
    await expect(plan(page)).toBeFocused()
    await page.keyboard.type(' (XLSX)')
    await expect(plan(page).locator('li').filter({ hasText: "Excel's own format (XLSX), which" })).toBeVisible()
    await comments(page)
        .filter({ hasText: 'name the ticket' })
        .getByRole('button', { name: 'resolve', exact: true })
        .click()
    await expect(plan(page)).toBeFocused()
})

test('the bubble shows just over the selection', async ({ page }) => {
    await select(page, "Excel's own format")
    const bubble = page.getByTestId('plan-bubble')
    await expect(bubble).toBeVisible()
    const passage = await page.evaluate(() => {
        const box = globalThis.getSelection()?.getRangeAt(0).getBoundingClientRect()
        return box === undefined ? undefined : { left: box.left, right: box.right, top: box.top }
    })
    // Its bottom a few pixels over the passage's top, and centred on it within a pixel, not across the page.
    await expect(async () => {
        const box = await bubble.boundingBox()
        expect(passage).toBeDefined()
        expect(box).not.toBeNull()
        if (passage === undefined || box === null) {
            return
        }
        const gap = passage.top - (box.y + box.height)
        expect(gap).toBeGreaterThanOrEqual(0)
        expect(gap).toBeLessThan(16)
        expect(Math.abs(box.x + box.width / 2 - (passage.left + passage.right) / 2)).toBeLessThanOrEqual(1)
    }).toPass()
})

test('the shortcut and the bubble over a selection both open a comment on it', async ({ page }) => {
    await select(page, 'Excel')
    await page.keyboard.press('ControlOrMeta+Alt+m')
    await expect(page.getByRole('form', { name: 'Comment' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('form', { name: 'Comment' })).toBeHidden()
    // Further down than the window shows, under the sticky foot: in view, as a passage the operator selects is.
    await plan(page).getByText('template cache').scrollIntoViewIfNeeded()
    await select(page, 'template cache')
    await page.getByTestId('plan-bubble').getByRole('button', { name: 'Comment' }).click()
    await expect(page.getByRole('form', { name: 'Comment' })).toBeVisible()
    await expect(page.getByTestId('plan-bubble')).toBeHidden()
})
