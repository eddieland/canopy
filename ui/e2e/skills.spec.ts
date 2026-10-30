import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// The mock's runtime finds five skills, one from each place a skill comes from (canopy/serve/mock/skills.py).

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('settings opens the skills page, which lists each skill with where its file is', async ({ page }) => {
    await page.goto('settings')
    await settled(page)
    await page.getByTestId('skills-open').click()
    await expect(page).toHaveURL(/\/settings\/skills$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Skills')
    await expect(page.getByTestId('skills').getByRole('listitem')).toHaveCount(5)

    const artifacts = page.getByTestId('skill-canopy-artifacts')
    await expect(artifacts).toContainText('.canopy/definitions-3f9c2a71/skills/canopy-artifacts/SKILL.md')
    await expect(artifacts).toContainText('Load before any artifact tool.')
    await expect(page.getByTestId('skill-terse')).toContainText('no description')
    await expect(page.getByTestId('skill-terse')).toContainText('~/.agents/skills/terse/SKILL.md')
})

test('a skill opens its instructions as text, and the filter narrows the list', async ({ page }) => {
    await page.goto('settings/skills')
    await settled(page)
    const notes = page.getByTestId('skill-release-notes')
    await notes.getByRole('button', { name: 'Show SKILL.md' }).click()
    await expect(notes.getByRole('region', { name: "release-notes's instructions" })).toContainText(
        'add a line to CHANGELOG.md',
    )
    await notes.getByRole('button', { name: 'Hide SKILL.md' }).click()

    await page.getByRole('searchbox', { name: 'Filter skills by name or description' }).fill('jira')
    await expect(page).toHaveURL(/\?q=jira$/u)
    await expect(page.getByTestId('skills').getByRole('listitem')).toHaveCount(1)
    await expect(page.getByTestId('skill-tracker-jira')).toBeVisible()
})
