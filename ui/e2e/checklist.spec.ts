import { expect, test } from '@playwright/test'

import { openRepoPicker, settled, signIn } from './helpers.ts'

// The mock journal's answers (canopy/serve/mock/checklists.py): `api`'s list, answered by ABC-102's run, and `web`'s,
// by T0's four ended worker runs in it, every one on T0's day, so every window holds them. Each run's page lists its
// own. The page opens on two weeks.

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("Reports opens the checklist's counts, each repository's items in its list's order", async ({ page }) => {
    await page.goto('reports')
    await settled(page)
    await page.getByTestId('reports-checklist-link').click()
    await expect(page).toHaveURL(/\/reports\/checklist$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Checklist')
    await expect(
        page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Checklist' }),
    ).toHaveAttribute('data-status', 'active')
    await expect(page.getByText('8 items in 2 repositories over 14 days · 2 held')).toBeVisible()
    await expect(page.getByTestId('checklist-window-14')).toHaveAttribute('data-state', 'on')

    const repos = page.getByTestId('checklist-repo')
    await expect(repos).toHaveCount(2)
    await expect(repos.first().getByRole('rowheader').first()).toHaveText('api4 items')
    await expect(repos.last().getByTestId('checklist-item').getByRole('rowheader')).toHaveText([
        'no-fixed-sleeps',
        'query-keys',
        'no-any',
        'i18n-strings',
    ])
    // item, reminded, answers, pass, fixed, held, n/a, unanswered, verdict
    const i18n = repos.last().getByTestId('checklist-item').filter({ hasText: 'i18n-strings' })
    await expect(i18n.getByRole('cell')).toHaveText([
        '4',
        '1 fixed · 2 n/a · 1 unanswered',
        '0',
        '1',
        '0',
        '2',
        '1',
        '',
    ])
    const table = page.getByTestId('checklist-table')
    await expect(table.getByRole('columnheader')).toHaveText([
        'item',
        'reminded',
        'answers',
        'pass',
        'fixed',
        'held',
        'n/a',
        'unanswered',
        'verdict',
    ])
})

test('a held count opens the runs that held the item, each with the reason it gave', async ({ page }) => {
    await page.goto('reports/checklist')
    await settled(page)
    const noAny = page.getByTestId('checklist-item').filter({ hasText: 'no-any' })
    await noAny.getByRole('button', { name: '1 held: the runs' }).click()
    const runs = page.getByTestId('checklist-runs')
    await expect(runs.getByRole('link')).toHaveText(['run:38'])
    await expect(runs).toContainText('typing them by hand is ABC-112.')
    await runs.getByRole('link', { name: 'run:38' }).click()
    await expect(page).toHaveURL(/\/workspace\/runs\/38$/u)
})

test("the sort orders each list's items, and an item's name shows its answers by week", async ({ page }) => {
    await page.goto('reports/checklist')
    await settled(page)
    await page.getByTestId('checklist-sort-unanswered').click()
    await expect(page).toHaveURL(/\/reports\/checklist\?sort=unanswered$/u)
    const web = page.getByTestId('checklist-repo').last()
    await expect(web.getByTestId('checklist-item').getByRole('rowheader').first()).toHaveText('i18n-strings')

    const weeks = page.getByTestId('checklist-weeks')
    await expect(weeks.getByTestId('checklist-weeks-of')).toHaveText('every item')
    await web.getByRole('link', { name: 'no-any' }).click()
    await expect(page).toHaveURL(/\/reports\/checklist\?sort=unanswered&item=web%3Ano-any$/u)
    await expect(web.getByRole('link', { name: 'no-any' })).toHaveAttribute('aria-current', 'page')
    await expect(weeks.getByTestId('checklist-weeks-of')).toHaveText('web · no-any')
    // The window's three ISO weeks, every answer in T0's: three pass and one held.
    await weeks.getByRole('button', { name: 'Show 3 weeks as a table' }).click()
    await expect(weeks.getByTestId('checklist-week-table').getByRole('row').last().getByRole('cell')).toHaveText([
        '4',
        '3',
        '0',
        '1',
        '0',
        '0',
    ])

    // Every item again, from the panel's header.
    await weeks.getByRole('link', { name: 'every item' }).click()
    await expect(page).toHaveURL(/\/reports\/checklist\?sort=unanswered$/u)
    await expect(weeks.getByTestId('checklist-weeks-of')).toHaveText('every item')
})

test("a run's page lists what it answered of its list, a held item's reason under it", async ({ page }) => {
    await page.goto('workspace/runs/38')
    await settled(page)
    const checklist = page.getByTestId('run-checklist')
    await expect(checklist.getByRole('heading', { level: 2 })).toHaveText('Checklist')
    await expect(page.getByTestId('run-checklist-said')).toHaveText('web · 1 pass · 1 fixed · 1 held · 1 n/a')
    const rows = checklist.getByTestId('checklist-answer')
    await expect(rows).toHaveText([
        /^passno-fixed-sleeps$/u,
        /^fixedquery-keys$/u,
        /^heldno-any.*typing them by hand is ABC-112\.$/u,
        /^n\/ai18n-strings$/u,
    ])
    // Under the run's facts, over its transcript.
    const panels = await page.locator('main h2').allTextContents()
    expect(panels.slice(panels.indexOf('Run'), panels.indexOf('Run') + 3)).toEqual(['Run', 'Checklist', 'Transcript'])

    // A run given no list has no panel.
    await page.goto('workspace/runs/41')
    await settled(page)
    await expect(page.getByTestId('run-checklist')).toHaveCount(0)
})

test('the window and the repository filter narrow the counts, and keep each other', async ({ page }) => {
    await page.goto('reports/checklist')
    await settled(page)
    await page.getByTestId('checklist-window-30').click()
    await expect(page).toHaveURL(/\/reports\/checklist\?days=30$/u)
    await expect(page.getByText('8 items in 2 repositories over 30 days · 2 held')).toBeVisible()

    const picker = await openRepoPicker(page.getByRole('button', { name: /^Filter by repository: /u }))
    await picker.getByRole('option', { name: 'web', exact: true }).click()
    await page.keyboard.press('Escape')
    await expect(page).toHaveURL(/\/reports\/checklist\?days=30&repo=web$/u)
    const repos = page.getByTestId('checklist-repo')
    await expect(repos).toHaveCount(1)
    await expect(repos.getByRole('rowheader').first()).toHaveText('web4 items')

    // The default window needs no search; the filter stays.
    await page.getByTestId('checklist-window-14').click()
    await expect(page).toHaveURL(/\/reports\/checklist\?repo=web$/u)
    await expect(repos).toHaveCount(1)
})

test('a repository whose runs answered no list says so, and so does a window with no list answered', async ({
    page,
}) => {
    await page.goto('reports/checklist?repo=mobile')
    await expect(page.getByTestId('checklist-items')).toContainText(
        'no run in mobile was given a checklist in these 14 days',
    )
    await expect(page.getByTestId('checklist-table')).toHaveCount(0)

    await page.route('**/api/reports/checklist*', (route) =>
        route.fulfill({
            json: {
                since: '2026-09-25T00:00:00Z',
                until: '2026-10-09T00:00:00Z',
                days: 14,
                repo: null,
                items: [],
                weeks: [],
                previous: {
                    since: '2026-09-11T00:00:00Z',
                    until: '2026-09-25T00:00:00Z',
                    reminded: 0,
                    held: 0,
                    unanswered: 0,
                },
            },
        }),
    )
    await page.goto('reports/checklist')
    await expect(page.getByTestId('checklist-items')).toContainText(
        "no worker run of these 14 days was given a checklist: each repository's is a file in paths.checklists",
    )
    await expect(page.getByText('no checklist answered over 14 days')).toBeVisible()
    await expect(page.getByRole('button', { name: /^Filter by repository: /u })).toHaveCount(0)
})
