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

test("a public ticket's page says where a reply goes one way: its chip on hover and its reply box agree", async ({
    page,
}) => {
    await page.goto('tickets/ABC-105')
    await settled(page)
    // The description is the ticket's state; what public means is the chip's, on hover and to a screen reader.
    await expect(page.locator('main header p')).toHaveText(/^plan waiting on you · active \d+\w+ ago$/u)
    const chip = page.locator('main header [title]').filter({ hasText: /^public/u })
    const hint = /comments stay on the tracker; a reply you send here stays in canopy/u
    await expect(chip).toHaveAttribute('title', hint)
    await expect(chip).toContainText(hint)
    await expect(page.getByRole('textbox', { name: 'Reply' })).toHaveAttribute(
        'placeholder',
        'For its next worker, as an instruction. It stays in canopy, never on the ticket.',
    )
})

test("a PR's URL in a worker's report is named as the PR is anywhere: its page, then GitHub", async ({ page }) => {
    await page.goto('tickets/ABC-103')
    await settled(page)
    const url = 'https://github.com/acme/web/pull/91'
    const conversation = page.getByTestId('conversation')
    const out = conversation.getByRole('link', { name: 'acme/web#91 on GitHub' })
    await expect(out).toHaveAttribute('href', url)
    await expect(out).toHaveAttribute('target', '_blank')
    await expect(out).toHaveAttribute('rel', 'noreferrer noopener')
    await conversation.getByRole('link', { name: 'acme/web#91', exact: true }).click()
    await expect(page).toHaveURL(/\/pull-requests\/pr\?url=/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(
        'acme/web#91 ABC-103: move billing to v2 and drop the v1 client',
    )
})

test("a ticket's conversation ends on the run working it now, and only while one is", async ({ page }) => {
    await page.goto('tickets/ABC-101')
    await settled(page)
    const working = page.getByTestId('working-41')
    await expect(working).toContainText('working now')
    await expect(working).toContainText('implement')
    await working.getByRole('link', { name: 'run:41' }).click()
    await expect(page).toHaveURL(/\/workspace\/runs\/41$/u)

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
    // A refetch of the ticket can still be in the padding route when the page closes (padMessages).
    await page.unrouteAll({ behavior: 'ignoreErrors' })
})

test('a reply is written in the Markdown the thread draws: formatted from the keyboard, undone, and previewed', async ({
    page,
}) => {
    await page.goto('tickets/ABC-103')
    await settled(page)
    const field = page.getByRole('textbox', { name: 'Reply' })
    await field.fill('use the v2 API')
    await field.press('Shift+Home')
    await field.press('ControlOrMeta+b')
    await expect(field).toHaveValue('**use the v2 API**')
    // The browser makes the edit, so its own undo takes it back, as it does typing.
    await field.press('ControlOrMeta+z')
    await expect(field).toHaveValue('use the v2 API')

    await field.fill('- first')
    await field.press('Shift+Enter')
    await field.pressSequentially('second')
    await expect(field).toHaveValue('- first\n- second')

    const form = page.getByRole('form', { name: 'Reply' })
    await form.getByRole('radio', { name: 'Preview' }).click()
    await expect(form.getByRole('region', { name: 'Preview' }).getByRole('listitem')).toHaveText(['first', 'second'])
    await form.getByRole('radio', { name: 'Write' }).click()
    await expect(field).toHaveValue('- first\n- second')
})
