import { expect, test } from '@playwright/test'

import { padMessages, settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the operator's own words sit on the right of the thread, everyone else's on the left", async ({ page }) => {
    await page.goto('tickets/ABC-103')
    await settled(page)
    const thread = page.getByTestId('conversation')
    const mine = await thread.locator('[data-source=operator]').first().boundingBox()
    const theirs = await thread.locator('[data-source=worker]').first().boundingBox()
    const all = await thread.boundingBox()
    if (!mine || !theirs || !all) {
        throw new Error('the thread did not render')
    }
    expect(Math.round(mine.x + mine.width)).toBe(Math.round(all.x + all.width - 12))
    expect(Math.round(theirs.x)).toBe(Math.round(all.x + 12))
})

test("a URL in a worker's report is a link to itself, opening in a new tab", async ({ page }) => {
    await page.goto('tickets/ABC-103')
    await settled(page)
    const link = page.getByTestId('conversation').getByRole('link', { name: 'https://github.com/acme/web/pull/91' })
    await expect(link).toHaveAttribute('href', 'https://github.com/acme/web/pull/91')
    await expect(link).toHaveAttribute('target', '_blank')
    await expect(link).toHaveAttribute('rel', 'noreferrer noopener')
})

test("a ticket's conversation ends on the run working it now, and only while one is", async ({ page }) => {
    await page.goto('tickets/ABC-101')
    await settled(page)
    const working = page.getByTestId('working-41')
    await expect(working).toContainText('working now')
    await expect(working).toContainText('implement')
    await working.getByRole('link', { name: 'run:41' }).click()
    await expect(page).toHaveURL(/\/runs\/41$/u)

    await page.goto('tickets/ABC-103')
    await settled(page)
    await expect(page.getByTestId('conversation')).toBeVisible()
    await expect(page.getByTestId('working-now')).toBeHidden()
})

test('a long conversation scrolls in its panel, opening at its newest end, which a flip moves', async ({ page }) => {
    await padMessages(page, 'ABC-102', 30)
    await page.goto('tickets/ABC-102')
    await settled(page)
    const region = page.getByRole('region', { name: 'Conversation' })
    const reply = page.getByTestId('ticket-conversation').getByRole('textbox')
    // It scrolls on its own, at its end, and the newest message shows on one screen with the reply form under it.
    expect(await region.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)
    // Within a pixel: scrollTop can be fractional where the heights are whole.
    await expect
        .poll(() => region.evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop))
        .toBeLessThanOrEqual(1)
    await reply.scrollIntoViewIfNeeded()
    await expect(reply).toBeInViewport()
    await expect(page.getByTestId('message-1029')).toBeInViewport()
    await expect(page.getByTestId('message-1000')).not.toBeInViewport()

    await page.getByTestId('order-conversation').click()
    await expect(region).toHaveJSProperty('scrollTop', 0)
    await expect(page.getByTestId('message-1029')).toBeInViewport()
})
