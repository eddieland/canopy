import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// A workspace far past the mock's three repositories: pages that list a line per repository or per slot must keep
// what the operator came for in reach, and nothing past the panel's edge.

const POOLS = 40
const SLOTS = 60
// Slot #N of a busy pool: working, idle, broken, idle, idle, idle, then held, over again. None is dirty.
const BUSY = ['working', 'idle', 'broken', 'idle', 'idle', 'idle', 'held']
// How many slots of a busy pool are broken.
const BROKEN = Array.from({ length: SLOTS }, (_, s) => BUSY[s % BUSY.length]).filter((s) => s === 'broken').length

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('a workspace of many pools keeps every slot strip inside the panel, and folds idle slots', async ({ page }) => {
    // About the narrowest window the UI holds up in (DESIGN.md).
    await page.setViewportSize({ width: 820, height: 800 })
    await manyPools(page)
    await page.goto('worktrees')
    await settled(page)
    const panel = page.getByTestId('pools')
    await expect(panel.getByRole('region')).toHaveCount(POOLS)

    // A strip of sixty squares wraps rather than pushing past the panel's edge.
    const overflow = await panel.evaluate((el) => {
        const edge = el.getBoundingClientRect().right
        return [...el.querySelectorAll('*')].filter((child) => child.getBoundingClientRect().right > edge + 0.5).length
    })
    expect(overflow).toBe(0)

    // A pool of idle slots alone is its header and one line, which opens each slot's own.
    const idle = page.getByTestId('pool-repo-00')
    await expect(idle.getByTestId(/^worktree-/u)).toHaveCount(0)
    const fold = idle.getByRole('button', { name: `Show ${SLOTS} slots, #1 to #${SLOTS}` })
    await expect(fold).toHaveAttribute('aria-expanded', 'false')
    await fold.click()
    await expect(idle.getByTestId(/^worktree-/u)).toHaveCount(SLOTS)
    await expect(idle.getByRole('button', { name: `Hide ${SLOTS} slots, #1 to #${SLOTS}` })).toHaveAttribute(
        'aria-expanded',
        'true',
    )

    // In a busy pool, three idle slots in a row fold; one or two stay as they are.
    const busy = page.getByTestId('pool-repo-01')
    await expect(busy.getByTestId('idle-slots-4')).toContainText('3 slots, #4 to #6')
    await expect(busy.getByTestId('worktree-2')).toHaveAttribute('data-state', 'idle')
})

test('the worktrees filter keeps the slots in a state, and the pools that have one', async ({ page }) => {
    await manyPools(page)
    await page.goto('worktrees')
    await settled(page)
    await page.getByRole('navigation', { name: 'Filter by state' }).getByRole('link', { name: 'broken' }).click()
    await expect(page).toHaveURL(/\/worktrees\?state=broken$/u)

    const panel = page.getByTestId('pools')
    // Every busy pool has broken slots; the idle ones are gone.
    await expect(panel.getByRole('region')).toHaveCount(POOLS / 2)
    await expect(page.getByTestId('pool-repo-00')).toHaveCount(0)
    // Every broken slot of every busy pool, and nothing else.
    const rows = panel.getByTestId(/^(?:worktree-\d+|idle-slots-\d+)$/u)
    await expect(rows).toHaveCount((POOLS / 2) * BROKEN)
    for (const state of await rows.evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset['state']))) {
        expect(state).toBe('broken')
    }
    // A pool's header still counts every slot.
    await expect(page.getByTestId('pool-repo-01').getByTestId('slot-strip').locator('span')).toHaveCount(SLOTS)

    await page.goto('worktrees?state=dirty')
    await settled(page)
    await expect(panel).toContainText('no dirty slots now')
})

test('a ticket across many repositories keeps its Work panel and reply in reach', async ({ page }) => {
    const repos = 20
    await page.route('**/api/tickets/ABC-102', async (route) => {
        const response = await route.fetch()
        const body = (await response.json()) as { units: object[] }
        body.units = Array.from({ length: repos }, (_, i) => ({
            repo: `repo-${i}`,
            pr_url: `https://github.com/acme/repo-${i}/pull/${100 + i}`,
            phase: 'pr_open',
        }))
        await route.fulfill({ response, json: body })
    })
    await page.goto('tickets/ABC-102')
    await settled(page)

    // The tracker's link, then every PR in one menu.
    const links = page.getByRole('navigation', { name: 'Links out' })
    await expect(links.getByRole('link')).toHaveCount(1)
    const prs = links.getByRole('button', { name: `${repos} PRs` })
    await prs.click()
    const menu = page.getByRole('menu')
    await expect(menu.getByRole('menuitem')).toHaveCount(repos)
    const first = menu.getByRole('menuitem', { name: 'acme/repo-0#100' })
    await expect(first).toHaveAttribute('href', 'https://github.com/acme/repo-0/pull/100')
    await expect(first).toHaveAttribute('target', '_blank')
    await page.keyboard.press('Escape')
    await expect(menu).toHaveCount(0)
    await expect(prs).toBeFocused()

    // Every repository's PR is in the Work panel, scrolling in place under its branch.
    const units = page.getByRole('region', { name: 'Repositories' })
    await expect(units.getByRole('link', { name: /^acme\/repo-\d+#\d+$/u })).toHaveCount(repos)
    expect(await units.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)
    // So the conversation under the Work panel, and the answer in it, stays in reach.
    await expect(page.getByTestId('ticket-conversation')).toBeInViewport()
})

test('a run holding a slot in many repositories names a few of them in its row', async ({ page }) => {
    // On its ticket's page: the runs page's list is the stream's, which would write over a stubbed read.
    await page.route('**/api/tickets/ABC-101', async (route) => {
        const response = await route.fetch()
        const body = (await response.json()) as { runs: { id: number; worktrees: string[] }[] }
        const run = body.runs.find((r) => r.id === 41)
        if (run === undefined) {
            throw new Error("the mock has no run 41 on ABC-101's page")
        }
        run.worktrees = Array.from({ length: 12 }, (_, i) => `.treehouse/repo-${i}-abc/1/repo-${i}`)
        await route.fulfill({ response, json: body })
    })
    await page.goto('tickets/ABC-101')
    await settled(page)
    const row = page.getByTestId('ticket-runs').getByTestId('run-41')
    await expect(row).toContainText('.treehouse/repo-0-abc/1/repo-0')
    await expect(row).toContainText('.treehouse/repo-2-abc/1/repo-2')
    await expect(row).not.toContainText('.treehouse/repo-3-abc/1/repo-3')
    const more = row.getByTestId('run-worktrees-more')
    await expect(more).toHaveText('+9 more worktrees')
    await expect(more).toHaveAttribute('title', /repo-11-abc\/1\/repo-11$/u)
})

/**
 * Serves `POOLS` pools of `SLOTS` slots each, made from the mock's own slots so every field is one the server sends.
 * Even pools are idle throughout; odd ones cycle through every state but dirty, with three idle slots in a row from #4.
 */
async function manyPools(page: Page): Promise<void> {
    await page.route('**/api/worktrees', async (route) => {
        const response = await route.fetch()
        const mock = (await response.json()) as { repo: string; worktrees: { name: string; state: string }[] }[]
        const slots = mock.flatMap((p) => p.worktrees)
        const like = (state: string) => {
            const found = slots.find((w) => w.state === state)
            if (found === undefined) {
                throw new Error(`the mock has no ${state} slot`)
            }
            return found
        }
        const pools = Array.from({ length: POOLS }, (_, p) => ({
            repo: `repo-${String(p).padStart(2, '0')}`,
            size: SLOTS,
            error: null,
            worktrees: Array.from({ length: SLOTS }, (__, s) => {
                const state = p % 2 === 0 ? 'idle' : (BUSY[s % BUSY.length] ?? 'idle')
                // The mock has no broken slot: a dirty one renamed, as treehouse's `missing` would read.
                const slot = state === 'broken' ? { ...like('dirty'), state, status: 'missing' } : like(state)
                const name = String(s + 1)
                return { ...slot, name, path: `.treehouse/repo-${p}-abc/${name}/repo-${p}` }
            }),
        }))
        await route.fulfill({ response, json: pools })
    })
}
