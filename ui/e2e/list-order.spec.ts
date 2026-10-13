import { expect, type Locator, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

async function testIds(rows: Locator): Promise<(string | null)[]> {
    return rows.evaluateAll((elements) => elements.map((e) => e.getAttribute('data-testid')))
}

test("a list's order flips from its header, keeps across a reload, and leaves other lists' as they were", async ({
    page,
}) => {
    await page.goto('tickets/ABC-102')
    await settled(page)
    const messages = page.getByTestId('conversation').locator('> li')
    const toggle = page.getByTestId('order-conversation')
    await expect(toggle).toHaveText('oldest first')
    expect(await testIds(messages)).toEqual(['message-4', 'message-5'])

    await toggle.click()
    await expect(toggle).toHaveText('newest first')
    expect(await testIds(messages)).toEqual(['message-5', 'message-4'])

    await page.reload()
    await settled(page)
    await expect(toggle).toHaveText('newest first')
    expect(await testIds(messages)).toEqual(['message-5', 'message-4'])

    // The ticks keep their own order, newest first.
    await page.goto('ticks')
    await settled(page)
    await expect(page.getByTestId('order-ticks')).toHaveText('newest first')
    expect(await testIds(page.getByTestId('ticks').locator('> li'))).toEqual(['tick-2', 'tick-1'])

    await page.getByTestId('order-ticks').click()
    expect(await testIds(page.getByTestId('ticks').locator('> li'))).toEqual(['tick-1', 'tick-2'])
})
