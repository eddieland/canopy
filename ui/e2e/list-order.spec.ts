import { expect, test } from '@playwright/test'
import type { Locator } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

function testIds(rows: Locator): Promise<(string | undefined)[]> {
    return rows.evaluateAll((elements) => elements.map((e) => e.dataset.testid))
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
    await page.goto('workspace/ticks')
    await settled(page)
    await expect(page.getByTestId('order-ticks')).toHaveText('newest first')
    expect(await testIds(page.getByTestId('ticks').locator('> li'))).toEqual(['tick-2', 'tick-1'])

    await page.getByTestId('order-ticks').click()
    expect(await testIds(page.getByTestId('ticks').locator('> li'))).toEqual(['tick-1', 'tick-2'])
})

test('a list by latest activity says it runs by the most recently updated, not the newest', async ({ page }) => {
    await page.goto('tickets')
    await settled(page)
    const toggle = page.getByTestId('order-tickets')
    await expect(toggle).toHaveText('recently updated')
    await toggle.click()
    await expect(toggle).toHaveText('least recently updated')
})

test("the reviews, and a PR's reviews, flip like any list in time", async ({ page }) => {
    await page.goto('pull-requests/reviews')
    await settled(page)
    const reviews = page.getByTestId('reviews').locator('> li')
    const first = await testIds(reviews)
    await expect(page.getByTestId('order-reviews')).toHaveText('newest first')
    await page.getByTestId('order-reviews').click()
    expect(await testIds(reviews)).toEqual(first.toReversed())

    await page.goto(`pull-requests/pr?url=${encodeURIComponent('https://github.com/acme/web/pull/88')}`)
    await settled(page)
    const own = page.getByTestId('pull-request-reviews').getByTestId('reviews').locator('> li')
    expect(await testIds(own)).toEqual(['pull-request-review-4', 'pull-request-review-1'])
    await page.getByTestId('order-pr-reviews').click()
    expect(await testIds(own)).toEqual(['pull-request-review-1', 'pull-request-review-4'])
})
