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
    await expect(card).toContainText('16% of 12 cores over 5 minutes, steady')
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
    await expect(page.getByTestId('counter-load')).toContainText('16%')
    await expect(page.getByTestId('counter-disk')).toContainText('where the workspace and the journal are')
    const disks = page.getByTestId('disk-row')
    await expect(disks).toHaveCount(2)
    await expect(disks.first()).toContainText('the workspace and the journal')
    await expect(disks.first()).toContainText('Under 2.0 GiB free, a tick runs no overseer')
    await expect(disks.nth(1)).toContainText('the temporary directory')
    await expect(disks.nth(1)).not.toContainText('a tick runs no overseer')
})

test("the graphs draw the server's last hour of readings, and say the one under the pointer", async ({ page }) => {
    await page.goto('system')
    await settled(page)
    const graphs = page.getByTestId('host-graphs').getByTestId('trend-chart')
    // The load, the memory, the loop's own, and each of the mock's two disks.
    await expect(graphs).toHaveCount(5)
    const load = graphs.first()
    await expect(load.getByTestId('trend-value')).toHaveText(/^20% now · peak \d+%$/u)
    await expect(load).toContainText('60 min ago')

    const plot = load.getByTestId('trend-plot')
    const box = await plot.boundingBox()
    expect(box).not.toBeNull()
    await plot.hover({ position: { x: (box?.width ?? 0) / 2, y: 10 } })
    await expect(load.getByTestId('trend-value')).toHaveText(/ at \d{2}:\d{2}$/u)
})

test('the processes show what keeps the machine busy as a tree, every one on asking, and fold under a parent', async ({
    page,
}) => {
    await page.goto('system')
    await settled(page)
    const panel = page.getByTestId('host-processes')
    await expect(panel).toContainText('2.2 of 12 cores busy over 10 s')
    const rows = panel.getByTestId('process-row')
    // The mock's twenty, but the four idle services: the build's compilers, the agents, and the parents above them.
    await expect(rows).toHaveCount(16)
    await expect(panel.getByTestId('process-hidden')).toHaveText('4 processes using under 1% of a core left out.')
    await expect(rows.filter({ hasText: 'rustc' }).first()).toContainText('running')
    await expect(rows.filter({ hasText: 'git fetch' })).toContainText('waiting on a disk')
    await expect(rows.filter({ has: page.getByTestId('process-loop') })).toContainText('48213')

    await panel.getByRole('button', { name: 'All' }).click()
    await expect(rows).toHaveCount(20)
    await expect(panel.getByTestId('process-hidden')).toHaveCount(0)

    await panel.getByRole('button', { name: 'Fold canopy 48213' }).click()
    await expect(rows).toHaveCount(11)
    await expect(rows.filter({ has: page.getByTestId('process-loop') })).toContainText('+9 under it')
    await expect(panel.getByRole('button', { name: 'Unfold canopy 48213' })).toHaveAttribute('aria-expanded', 'false')
})
