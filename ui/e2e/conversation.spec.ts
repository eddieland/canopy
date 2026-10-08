import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

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
    if (!mine || !theirs || !all) throw new Error('the thread did not render')
    expect(Math.round(mine.x + mine.width)).toBe(Math.round(all.x + all.width - 12))
    expect(Math.round(theirs.x)).toBe(Math.round(all.x + 12))
})
