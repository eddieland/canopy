import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

// A row's cells as a person reads them: its head, then each cell but a bar's, which is the eye's alone.
const READ = 'th, td:not([aria-hidden])'

test("the nav opens Skills under Reports: the week's skills by what their front matter cost", async ({ page }) => {
    await page.goto('reports')
    await settled(page)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Skills' }).click()
    await expect(page).toHaveURL(/\/reports\/skills$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Skills')
    // The mock's day of offers and loads on the runs it has (canopy/serve/mock/skill_use.py).
    await expect(page.locator('main header p')).toHaveText(
        '8 skills offered over 7 days · 4 never loaded · ~88.6k tokens of front matter',
    )
    await expect(page.getByTestId('skills-window-7')).toHaveAttribute('data-state', 'on')
    const rows = page.getByTestId('skills-skill-table').getByRole('rowheader')
    // The costliest front matter first: web's own skill, which one run in eleven loaded.
    await expect(rows.first()).toHaveText('design-system')
    await expect(page.getByTestId('skills-skill-design-system').locator(READ)).toHaveText([
        'design-system',
        '11',
        '1',
        '9%',
        '231',
        '54.2k',
        '1',
        '2.4k',
        '',
    ])
    // The tracker's skill, which the prompts say to load first: most runs offered it did, and so did the tasks'.
    await expect(page.getByTestId('skills-skill-tracker-jira').locator(READ)).toHaveText([
        'tracker-jira',
        '19',
        '12',
        '63%',
        '26',
        '6.7k',
        '15',
        '12.2k',
        '',
    ])
    await expect(page.getByTestId('skills-skill-terse')).toContainText('never loaded')
    // Offered to three runs, none of them counted: nothing to say of its cost, which is not none.
    await expect(page.getByTestId('skills-skill-store-listing').locator(READ)).toHaveText([
        'store-listing',
        '3',
        '0',
        '0%',
        '98',
        '–',
        '0',
        '0',
        'never loaded',
    ])
    await expect(page.getByTestId('skills-coverage')).toContainText(
        'Front matter is counted over 10 of the 21 runs the runtime answered for',
    )
})

test('the skills are set against the agents, and each agent against what its list costs a call', async ({ page }) => {
    await page.goto('reports/skills')
    await settled(page)
    const grid = page.getByTestId('skills-grid')
    // An agent offered no skill, the overseer, heads no column.
    await expect(grid.getByRole('columnheader')).toHaveText([
        'skill',
        'worker',
        'worker-private',
        'planner',
        'reviewer',
        'chore',
        'chore-deps',
    ])
    await expect(page.getByTestId('skills-grid-design-system').locator(READ)).toHaveText([
        'design-system',
        '1/4',
        '0/1',
        '0/3',
        '0/3',
        '–',
        '–',
    ])
    // Offered and never loaded is an empty bar; not offered is no bar at all.
    await expect(page.getByTestId('skills-grid-design-system').getByTestId('cell-bar')).toHaveCount(4)
    const agents = page.getByTestId('skills-agent-table')
    await expect(agents.getByRole('rowheader')).toHaveText([
        'canopy-overseer',
        'canopy-worker',
        'canopy-worker-private',
        'canopy-planner',
        'canopy-reviewer',
        'canopy-chore',
        'canopy-chore-deps',
    ])
    await expect(page.getByTestId('skills-agent-canopy-worker').locator(READ)).toHaveText([
        'canopy-worker',
        '4',
        '4',
        '7',
        '3',
        '387',
        '49.6k',
        'cost counted over 2 of 4',
    ])
    // The planner's sessions are not read, so its list has no cost yet; the tasks' runs are never asked about.
    await expect(page.getByTestId('skills-agent-canopy-planner')).toContainText('cost counted over 0 of 5')
    await expect(page.getByTestId('skills-agent-canopy-overseer')).toContainText('offered no skill')
    await expect(page.getByTestId('skills-unasked')).toContainText('8 runs were never asked what they were offered')
})

test('the order and the window are kept in the address, and the grid keeps the order of the table', async ({
    page,
}) => {
    await page.goto('reports/skills')
    await settled(page)
    await page.getByTestId('skills-sort-rate').click()
    await expect(page).toHaveURL(/\/reports\/skills\?order=rate$/u)
    const first = (table: string) => page.getByTestId(table).getByRole('rowheader').first()
    // The lowest load rate first, the skills most offered among those nothing loaded.
    await expect(first('skills-skill-table')).toHaveText('terse')
    await expect(first('skills-grid')).toHaveText('terse')
    await page.getByTestId('skills-window-30').click()
    await expect(page).toHaveURL(/\/reports\/skills\?order=rate&days=30$/u)
    await expect(page.locator('main header p')).toHaveText(/^8 skills offered over 30 days · 4 never loaded · /u)
    // The workers' runs of the weeks before were offered skills with no length kept: more runs, no more counted.
    await expect(page.getByTestId('skills-coverage')).toContainText(
        'Front matter is counted over 10 of the 26 runs the runtime answered for',
    )
    await page.getByTestId('skills-sort-cost').click()
    await expect(page).toHaveURL(/\/reports\/skills\?days=30$/u)
    await expect(first('skills-skill-table')).toHaveText('design-system')
})

test('the reports page has a card for the Skills report, its line over 30 days', async ({ page }) => {
    await page.goto('reports')
    await settled(page)
    const card = page.getByTestId('reports-card-skills')
    await expect(page.getByTestId('reports-card-skills-line')).toHaveText(
        /^8 skills offered over 30 days · 4 never loaded · ~[\d.]+k tokens of front matter$/u,
    )
    await card.click()
    await expect(page).toHaveURL(/\/reports\/skills\?days=30$/u)
})
