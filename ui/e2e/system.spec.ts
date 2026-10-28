import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// The mock's machine is a fixed reading, nothing on it under pressure (canopy/serve/mock/host.py).

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('the header says the host is ok, shows the machine on hover, and opens the page', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const readout = page.getByTestId('host-readout')
    await expect(readout).toHaveText('host ok')
    await expect(readout).toHaveAccessibleName('host ok: system resources of build-box')

    await readout.hover()
    const card = page.getByTestId('host-card')
    await expect(card).toContainText('build-box')
    await expect(card).toContainText('2.41 1.87 1.52 on 12 cores')
    await expect(card).toContainText('412 GiB free of 931 GiB, the workspace and the journal')

    await readout.click()
    await expect(page).toHaveURL(/\/system$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('System resources')
})

test('the page shows each disk canopy writes to, and the floor a tick needs on the ones it checks', async ({
    page,
}) => {
    await page.goto('system')
    await settled(page)
    await expect(page.getByTestId('host-concerns')).toHaveCount(0)
    await expect(page.getByTestId('counter-load')).toContainText('1.87')
    await expect(page.getByTestId('counter-disk')).toContainText('where the workspace and the journal are')
    const disks = page.getByTestId('disk-row')
    await expect(disks).toHaveCount(2)
    await expect(disks.first()).toContainText('the workspace and the journal')
    await expect(disks.first()).toContainText('Under 2.0 GiB free, a tick runs no overseer')
    await expect(disks.nth(1)).toContainText('the temporary directory')
    await expect(disks.nth(1)).not.toContainText('a tick runs no overseer')
})
