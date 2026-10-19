import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('settings picks a 12-hour clock and the time zone, and every page reads its times so', async ({ page }) => {
    await page.goto('settings')
    await settled(page)
    const sample = page.getByTestId('clock-sample')
    await expect(sample).toHaveText(/ \d{2}:\d{2}$/u)

    await page.getByTestId('clock-12').click()
    await expect(sample).toHaveText(/ \d{1,2}:\d{2} [AP]M$/u)
    await page.getByRole('checkbox', { name: 'Show time zone' }).check()
    await expect(sample).toHaveText(/ \d{1,2}:\d{2} [AP]M \S+$/u)

    // A run's `when` field reads on the same clock, and keeps it after a reload.
    await page.goto('runs/39')
    await settled(page)
    const main = page.getByRole('main')
    await expect(main.getByText(/^\S+ \d{1,2} \d{1,2}:\d{2} [AP]M \S+$/u).first()).toBeVisible()
    await page.reload()
    await settled(page)
    await expect(main.getByText(/^\S+ \d{1,2} \d{1,2}:\d{2} [AP]M \S+$/u).first()).toBeVisible()

    await page.goto('settings')
    await settled(page)
    await page.getByTestId('clock-24').click()
    await page.getByRole('checkbox', { name: 'Show time zone' }).uncheck()
    await expect(sample).toHaveText(/ \d{2}:\d{2}$/u)
})
