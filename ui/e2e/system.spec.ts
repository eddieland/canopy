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

test('the page says nothing is under pressure, then each disk canopy writes to with its hour and floor', async ({
    page,
}) => {
    await page.goto('system')
    await settled(page)
    await expect(page.getByTestId('host-concerns')).toHaveCount(0)
    await expect(page.getByTestId('host-calm')).toContainText('Nothing under pressure.')
    await expect(page.getByTestId('counter-load')).toContainText('16%')
    await expect(page.getByTestId('counter-load')).toContainText('1.87 over 5 min, steady')
    await expect(page.getByTestId('counter-loop')).toHaveCount(0)
    await expect(page.getByTestId('counter-disk')).toContainText('where the workspace and the journal are')
    const disks = page.getByTestId('disk-row')
    await expect(disks).toHaveCount(2)
    await expect(disks.first()).toContainText('the workspace and the journal')
    await expect(disks.first()).toContainText('Under 2.0 GiB free, a tick runs no overseer')
    await expect(disks.first().getByTestId('trend-chart')).toContainText('floor 2.0 GiB')
    await expect(disks.nth(1)).toContainText('the temporary directory')
    await expect(disks.nth(1)).not.toContainText('a tick runs no overseer')
    // The build filled the temporary directory and cleared it: its row names the hour's low, not the free it repeats.
    await expect(disks.nth(1).getByTestId('trend-value')).toHaveText(/^low \d+(\.\d)? GiB$/u)
    await expect(page.getByTestId('disk-fills')).toHaveCount(0)
})

test("the graphs draw the server's last hour in two ranks, and point at one moment on every one", async ({ page }) => {
    await page.goto('system')
    await settled(page)
    const panel = page.getByTestId('host-graphs')
    await expect(panel.getByTestId('host-graphs-read')).toHaveText(/^the last 60 min, read \d+s ago$/u)
    const graphs = panel.getByTestId('trend-chart')
    // The load, the memory, and the processors busy; then the swap, the two stalls, and the loop's own. A disk's is on
    // its row.
    await expect(graphs).toHaveCount(7)
    const load = graphs.first()
    await expect(load.getByTestId('trend-value')).toHaveText(/^20% now · peak \d+%$/u)
    await expect(graphs.nth(1)).toContainText('Memory used')
    await expect(graphs.nth(1)).toContainText('15% left')
    await expect(graphs.nth(2)).toContainText('CPU busy')
    await expect(graphs.nth(2).getByTestId('trend-value')).toHaveText(/^15% now · peak \d+%$/u)
    await expect(graphs.nth(3)).toContainText('Swap used')
    await expect(graphs.nth(5)).toContainText('Disk stalls')
    // The hour is said once, in the header, not under each graph.
    await expect(panel.getByText('60 min ago')).toHaveCount(0)

    const plot = load.getByTestId('trend-plot')
    const box = await plot.boundingBox()
    expect(box).not.toBeNull()
    await plot.hover({ position: { x: (box?.width ?? 0) / 2, y: 10 } })
    const at = load.getByTestId('trend-value')
    await expect(at).toHaveText(/ at \d{2}:\d{2}$/u)
    // Every graph points at the same moment: "was it the build at 14:05?" reads the load and the stalls together.
    const time = (await at.textContent())?.split(' at ')[1] ?? ''
    await expect(graphs.nth(5).getByTestId('trend-value')).toHaveText(new RegExp(` at ${time}$`, 'u'))
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
    await expect(rows.filter({ hasText: 'rg --line-number' })).toContainText('waiting on a disk')
    await expect(rows.filter({ has: page.getByTestId('process-loop') })).toContainText('48213')

    await panel.getByRole('button', { name: 'All' }).click()
    await expect(rows).toHaveCount(20)
    await expect(panel.getByTestId('process-hidden')).toHaveCount(0)

    await panel.getByRole('button', { name: 'Fold canopy 48213' }).click()
    await expect(rows).toHaveCount(11)
    await expect(rows.filter({ has: page.getByTestId('process-loop') })).toContainText('+9 under it')
    await expect(panel.getByRole('button', { name: 'Unfold canopy 48213' })).toHaveAttribute('aria-expanded', 'false')
})
