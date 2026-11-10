import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// The mock's machine is a fixed reading, caught mid-build (canopy/serve/mock/host.py): the temporary directory nearly
// full, the memory and the load high, and the workspace's disk calm.

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('the header says the disk is low, shows the machine on hover, and opens the page', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const readout = page.getByTestId('host-readout')
    await expect(readout).toHaveText('disk low')
    await expect(readout).toHaveAccessibleName('disk low: system resources of build-box')
    await expect(readout).toHaveAttribute('data-pressure', 'critical')

    await readout.hover()
    const card = page.getByTestId('host-card')
    await expect(card).toContainText('build-box')
    await expect(card).toContainText('768 MiB free where the temporary directory is')
    await expect(card).toContainText('114% of 12 cores over 5 minutes, rising')
    await expect(card).toContainText('412 GiB free of 931 GiB, the workspace and the journal')

    await readout.click()
    await expect(page).toHaveURL(/\/system$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('System resources')
})

test('the page says what is under pressure, worst first, then each disk canopy writes to with its hour', async ({
    page,
}) => {
    await page.goto('system')
    await settled(page)
    await expect(page.getByTestId('host-calm')).toHaveCount(0)
    // The red disk, then the amber memory and load; the workspace's disk, far above its floor, is not among them.
    await expect(page.getByTestId('host-concerns').getByRole('listitem')).toHaveText([
        /^768 MiB free where the temporary directory is/u,
        /^7\.3 GiB of 64 GiB memory available: a new agent or build may swap/u,
        /^load at 114% of 12 cores over five minutes: work waits for a processor/u,
    ])
    await expect(page.getByTestId('counter-load')).toContainText('114%')
    await expect(page.getByTestId('counter-load')).toContainText('13.71 over 5 min, rising')
    await expect(page.getByTestId('counter-memory')).toContainText('89%')
    await expect(page.getByTestId('counter-loop')).toHaveCount(0)
    await expect(page.getByTestId('counter-disk')).toContainText('768 MiB')
    await expect(page.getByTestId('counter-disk')).toContainText('where the temporary directory is')
    // A disk's concern puts the disks above the processes.
    await expect(page.locator('[data-testid="host-disks"] ~ [data-testid="host-processes"]')).toHaveCount(1)
    const disks = page.getByTestId('disk-row')
    await expect(disks).toHaveCount(2)
    await expect(disks.first()).toContainText('the workspace and the journal')
    await expect(disks.first()).toContainText('412 GiB free of 931 GiB')
    await expect(disks.first()).toContainText('Under 2.0 GiB free, a tick runs no overseer')
    await expect(disks.first().getByTestId('trend-chart')).toContainText('floor 2.0 GiB')
    await expect(disks.first().getByTestId('disk-fills')).toHaveCount(0)
    await expect(disks.nth(1)).toContainText('the temporary directory')
    await expect(disks.nth(1)).toContainText('768 MiB free of 32 GiB')
    await expect(disks.nth(1)).not.toContainText('a tick runs no overseer')
    // The build drained it over the hour, and at that rate it is full in minutes.
    await expect(disks.nth(1).getByTestId('disk-fills')).toHaveText('full in about 2 min at this rate')
})

test("the graphs draw the server's last hour of readings, and say the one under the pointer", async ({ page }) => {
    await page.goto('system')
    await settled(page)
    const graphs = page.getByTestId('host-graphs').getByTestId('trend-chart')
    // The load, the processors busy, the memory, the swap, the two stalls, and the loop's own; a disk's is on its row.
    await expect(graphs).toHaveCount(7)
    const load = graphs.first()
    await expect(load.getByTestId('trend-value')).toHaveText(/^122% now · peak \d+%$/u)
    await expect(load).toContainText('60 min ago')
    await expect(graphs.nth(1)).toContainText('CPU busy')
    await expect(graphs.nth(1).getByTestId('trend-value')).toHaveText(/^91% now · peak \d+%$/u)
    await expect(graphs.nth(3)).toContainText('Swap used')
    await expect(graphs.nth(5)).toContainText('Disk stalls')

    const plot = load.getByTestId('trend-plot')
    const box = await plot.boundingBox()
    expect(box).not.toBeNull()
    await plot.hover({ position: { x: (box?.width ?? 0) / 2, y: 10 } })
    await expect(load.getByTestId('trend-value')).toHaveText(/ at \d{2}:\d{2}$/u)
})

test("the processes are the loop's, a run's tied to it, then what else is busy; every one on asking", async ({
    page,
}) => {
    await page.goto('system')
    await settled(page)
    const panel = page.getByTestId('host-processes')
    await expect(panel).toContainText('10.7 of 12 cores busy over 10 s')
    await expect(panel.getByTestId('process-above')).toHaveText('under systemd › sshd › sshd › sshd › bash')
    const rows = panel.getByTestId('process-row')
    // The loop and its two runs' trees, then the editor's server elsewhere: the mock's twenty, but the loop's five
    // parents, named in one line over it, and four idle services.
    await expect(rows).toHaveCount(11)
    await expect(panel.getByTestId('process-hidden')).toHaveText('4 processes using under 1% of a core left out.')
    await expect(rows.filter({ has: page.getByTestId('process-loop') })).toContainText('48213')
    // Run 41's row is what the run costs: its agent, the build, and both compilers.
    const run = rows.filter({ has: page.getByRole('link', { name: 'run:41 ABC-101' }) })
    await expect(run).toContainText('python3')
    await expect(run).toContainText('1060%')
    await expect(rows.filter({ has: page.getByRole('link', { name: 'run:43 ABC-104' }) })).toHaveCount(1)
    await expect(rows.filter({ hasText: 'rustc' }).first()).toContainText('running')
    await expect(rows.filter({ hasText: 'rg --line-number' })).toContainText('waiting on a disk')
    await expect(panel.getByTestId('process-elsewhere').getByTestId('process-row')).toContainText('vite')

    await run.getByRole('link', { name: 'run:41 ABC-101' }).click()
    await expect(page).toHaveURL(/\/workspace\/runs\/41$/u)
    await page.goBack()
    await settled(page)

    await panel.getByRole('button', { name: 'All' }).click()
    await expect(rows).toHaveCount(20)
    await expect(panel.getByTestId('process-hidden')).toHaveCount(0)
    await expect(panel.getByTestId('process-elsewhere')).toHaveCount(0)

    await panel.getByRole('button', { name: 'Fold canopy 48213' }).click()
    await expect(rows).toHaveCount(11)
    await expect(rows.filter({ has: page.getByTestId('process-loop') })).toContainText('+9 under it')
    await expect(panel.getByRole('button', { name: 'Unfold canopy 48213' })).toHaveAttribute('aria-expanded', 'false')

    // As the operator left it, on coming back.
    await page.goto('attention')
    await page.goto('system')
    await settled(page)
    await expect(panel.getByRole('button', { name: 'All' })).toHaveAttribute('aria-pressed', 'true')
    await expect(rows).toHaveCount(11)
})
