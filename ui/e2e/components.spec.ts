import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('the components page draws each shared piece live, its Markdown fields previewing what they hold', async ({
    page,
}) => {
    await page.goto('components')
    await settled(page)
    for (const label of ['MarkdownField', 'Text fields', 'Button', 'Chip', 'Empty and None']) {
        await expect(page.getByText(label, { exact: true })).toBeVisible()
    }
    // The live field previews beside its text as it is written.
    const live = page.getByRole('textbox', { name: 'tall, live preview: a long brief' })
    await live.fill('- one\n- two')
    const preview = page.getByRole('region', { name: 'Preview' })
    await expect(preview.getByRole('listitem')).toHaveText(['one', 'two'])
})
