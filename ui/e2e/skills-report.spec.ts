import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

// A row's cells as a person reads them: its head, then each cell but a bar's, which is the eye's alone.
const READ = 'th, td:not([aria-hidden])'

test('the nav opens Skills under Reports: each agent by what its list costs a call, then each skill', async ({
    page,
}) => {
    await page.goto('reports')
    await settled(page)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Skills' }).click()
    await expect(page).toHaveURL(/\/reports\/skills$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Skills')
    // The mock's day of offers and loads on the runs it has (canopy/serve/mock/skill_use.py): the cost with the runs
    // it is counted in, since the rest have no model calls on record.
    await expect(page.locator('main header p')).toHaveText(
        '8 skills offered over 7 days · 4 never loaded · ' +
            'front matter ~348 tokens a call in 8 of 19 runs offered a skill',
    )
    await expect(page.getByTestId('skills-window-7')).toHaveAttribute('data-state', 'on')
    // The heaviest list a call first; the planner's sessions are not read, so its list has no cost yet; the
    // overseer is offered no skill, a known nothing.
    await expect(page.getByTestId('skills-agent-table').getByRole('rowheader')).toHaveText([
        'canopy-worker',
        'canopy-worker-private',
        'canopy-reviewer',
        'canopy-chore',
        'canopy-chore-deps',
        'canopy-planner',
        'canopy-overseer',
    ])
    await expect(page.getByTestId('skills-agent-canopy-worker').locator(READ)).toHaveText([
        'canopy-worker',
        '4',
        '0',
        '7',
        '3',
        '11',
        '387',
        '128',
        '49.6k',
    ])
    await expect(page.getByTestId('skills-agent-canopy-planner').locator(READ)).toHaveText([
        'canopy-planner',
        '8',
        '3',
        '7',
        '6',
        '5',
        '–',
        '–',
        '–',
    ])
    await expect(page.getByTestId('skills-agent-canopy-overseer').locator(READ)).toHaveText([
        'canopy-overseer',
        '2',
        '0',
        '0',
        '0',
        '0',
        '0',
        '–',
        '0',
    ])
    // Not known draws no bar; a known nothing, an empty one.
    await expect(page.getByTestId('skills-agent-canopy-planner').getByTestId('cell-bar')).toHaveCount(0)
    await expect(page.getByTestId('skills-agent-canopy-overseer').getByTestId('cell-bar')).toHaveCount(1)
    await expect(page.getByTestId('skills-offers')).toContainText('No offer on record for 9 of 30 runs')
})

test('the skills open on the costliest front matter, a skill no run loaded reading never', async ({ page }) => {
    await page.goto('reports/skills')
    await settled(page)
    const rows = page.getByTestId('skills-skill-table').getByRole('rowheader')
    // web's own skill leads: the most front matter, and one run in eleven loaded it.
    await expect(rows.first()).toHaveText('design-system')
    await expect(page.getByTestId('skills-skill-design-system').locator(READ)).toHaveText([
        'design-system',
        '11',
        '9%',
        '231',
        '234',
        '54.2k',
        '1',
        '0',
        '2.4k',
    ])
    // The tracker's skill, which the prompts say to load first: most runs offered it did, and so did the tasks'.
    await expect(page.getByTestId('skills-skill-tracker-jira').locator(READ)).toHaveText([
        'tracker-jira',
        '19',
        '63%',
        '26',
        '254',
        '6.7k',
        '15',
        '0',
        '12.2k',
    ])
    // Offered to three runs, none of them counted: nothing to say of its cost, which is not none.
    await expect(page.getByTestId('skills-skill-store-listing').locator(READ)).toHaveText([
        'store-listing',
        '3',
        'never',
        '98',
        '–',
        '–',
        '0',
        '0',
        '0',
    ])
    // The operator's own skill, denied to every agent: a call for it that failed, and no offer.
    await expect(page.getByTestId('skills-skill-canopy').locator(READ)).toHaveText([
        'canopy',
        '–',
        '–',
        '–',
        '–',
        '–',
        '0',
        '1',
        '0',
    ])
    await expect(page.getByTestId('skills-scope')).toHaveText('every agent')
    await expect(page.getByTestId('skills-count')).toHaveText('9')
    await expect(page.getByTestId('skills-coverage')).toHaveText(
        'Front matter is counted over 8 of the 19 runs offered a skill: 11 with no model calls on record. 1 load ' +
            'named no skill canopy could read: any skill here may be the one it loaded.',
    )
})

test("an agent's name narrows the skills to its own, least loaded first its list to deny, and back", async ({
    page,
}) => {
    await page.goto('reports/skills')
    await settled(page)
    await page.getByTestId('skills-agent-table').getByRole('link', { name: 'canopy-reviewer' }).click()
    await expect(page).toHaveURL(/\/reports\/skills\?agent=canopy-reviewer$/u)
    await expect(page.getByTestId('skills-scope')).toHaveText('canopy-reviewer')
    await expect(page.getByTestId('skills-count')).toHaveText('6 of 9')
    await page.getByTestId('skills-sort-least').click()
    await expect(page).toHaveURL(/\/reports\/skills\?agent=canopy-reviewer&order=least$/u)
    // The skills it was offered and never loaded, the costliest first, then the one it loads.
    await expect(page.getByTestId('skills-skill-table').getByRole('rowheader')).toHaveText([
        'design-system',
        'e2e-playwright',
        'release-notes',
        'write-a-skill',
        'terse',
        'tracker-jira',
    ])
    await expect(page.getByTestId('skills-skill-design-system').locator(READ)).toHaveText([
        'design-system',
        '3',
        'never',
        '231',
        '25',
        '5.8k',
        '0',
        '0',
        '0',
    ])
    await page.getByTestId('skills-skills').getByRole('link', { name: 'every agent' }).click()
    await expect(page).toHaveURL(/\/reports\/skills\?order=least$/u)
    await expect(page.getByTestId('skills-count')).toHaveText('9')
    // Over every agent, the skills nothing loaded lead, the costliest first.
    await expect(page.getByTestId('skills-skill-table').getByRole('rowheader').first()).toHaveText('canopy-artifacts')
})

test('the window is kept in the address beside the order, and 30 days say what they are counted over', async ({
    page,
}) => {
    await page.goto('reports/skills?order=most')
    await settled(page)
    // The prompts' skill is the most loaded.
    await expect(page.getByTestId('skills-skill-table').getByRole('rowheader').first()).toHaveText('tracker-jira')
    await page.getByTestId('skills-window-30').click()
    await expect(page).toHaveURL(/\/reports\/skills\?order=most&days=30$/u)
    await expect(page.locator('main header p')).toHaveText(
        '8 skills offered over 30 days · 4 never loaded · ' +
            'front matter ~348 tokens a call in 8 of 24 runs offered a skill',
    )
    // The workers' runs of the weeks before were offered skills with no length kept: more runs, no more counted.
    await expect(page.getByTestId('skills-coverage')).toContainText(
        "Front matter is counted over 8 of the 24 runs offered a skill: 5 from before canopy kept a skill's " +
            'length, 11 with no model calls on record.',
    )
})

test('the reports page has a card for the Skills report, its line over 30 days', async ({ page }) => {
    await page.goto('reports')
    await settled(page)
    await expect(page.getByTestId('reports-card-skills-line')).toHaveText(
        '8 skills offered over 30 days · 4 never loaded · ' +
            'front matter ~348 tokens a call in 8 of 24 runs offered a skill',
    )
    await page.getByTestId('reports-card-skills').click()
    await expect(page).toHaveURL(/\/reports\/skills\?days=30$/u)
})
