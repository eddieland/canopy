import { expect, test } from '@playwright/test'

import { openRepoPicker, plan, select } from './helpers.ts'

// Served under /canopy, signing nobody in, with the mock journal changing every 250 ms (playwright.config.ts). The
// writes happen here, not on the root server, whose screenshots need its journal as seeded.

test('the app works under a path prefix', async ({ page }) => {
    await page.goto('')
    await expect(page).toHaveURL(/\/canopy\/attention$/u)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Workspace' }).click()
    await expect(page).toHaveURL(/\/canopy\/workspace$/u)
    await page.reload()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Workspace')
})

test('stream events update the cache without refetching', async ({ page }) => {
    const fetches: string[] = []
    page.on('request', (request) => {
        if (request.resourceType() === 'fetch') {
            fetches.push(new URL(request.url()).pathname)
        }
    })
    await page.goto('workspace/runs')
    await expect(page.getByTestId('stream-status')).toHaveAttribute('data-status', 'open')

    // The mock journal adds a cent to run 41's cost every 250 ms: the page must follow it.
    const cost = page.getByTestId('run-41').getByTestId('run-cost')
    const seen = new Set<string>()
    await expect
        .poll(
            async () => {
                seen.add((await cost.textContent()) ?? '')
                return seen.size
            },
            { timeout: 5_000 },
        )
        .toBeGreaterThan(2)

    // One fetch of the runs on load; everything after came over the stream.
    expect(fetches.filter((path) => path.endsWith('/api/runs'))).toHaveLength(1)
})

test('a reply answers the waiting question, and a retry records nothing new', async ({ page }) => {
    await page.goto('tickets/ABC-102')
    await expect(page.getByTestId('conversation').getByText('waiting on you')).toBeVisible()
    const form = page.getByRole('form', { name: 'Reply' })
    await form.getByRole('textbox').fill('Blue, to match the toolbar.')
    await form.getByRole('button', { name: 'Reply' }).click()
    await expect(form.getByRole('status')).toContainText('answering message 5')
    const conversation = page.getByTestId('conversation')
    const mine = conversation.locator('[data-source=operator]').last()
    await expect(mine).toContainText('Blue, to match the toolbar.')
    await expect(mine).toContainText('via web')
    await expect(page.getByTestId('conversation').getByText('waiting on you')).toHaveCount(0)

    // No tick has read it yet: the reply says so, and the inbox keeps the question, marked answered, until one does.
    await expect(mine).toContainText('waiting for the next tick')
    await page.goto('attention')
    const item = page
        .getByTestId('attention-list')
        .getByRole('link')
        .filter({ hasText: 'awaiting reply' })
        .filter({ hasText: 'ABC-102' })
    await expect(item).toContainText('answered')
    await item.click()
    await expect(page.getByTestId('answered-note')).toContainText('leaves at the next tick')
})

test('a public ticket takes a reply that stays in canopy, and its tracker comment is shown as text', async ({
    page,
}) => {
    await page.goto('tickets/ABC-101')
    const form = page.getByRole('form', { name: 'Reply' })
    await expect(form.getByRole('textbox')).toHaveAttribute('placeholder', /never on the ticket/u)
    await form.getByRole('textbox').fill('Use your judgement on the review bot.')
    await form.getByRole('button', { name: 'Reply' }).click()
    await expect(form.getByRole('status')).toContainText('Recorded message')
    // Other tests reply to the same ticket at the same time, so find this reply by its text, not as the last one.
    await expect(
        page
            .getByTestId('conversation')
            .locator('[data-source=operator]')
            .filter({ hasText: 'Use your judgement on the review bot.' }),
    ).toHaveCount(1)
    const comment = page.getByTestId('message-6')
    // The fixture's comment holds markup: it must arrive as the characters, never as an element.
    await expect(comment).toContainText('<b>Thanks!</b>')
    await expect(comment.locator('b')).toHaveCount(0)
    await expect(comment).toContainText('data, authorizes nothing')
})

test('Enter sends a reply and Shift+Enter starts a new line', async ({ page }) => {
    await page.goto('tickets/ABC-101')
    const form = page.getByRole('form', { name: 'Reply' })
    await expect(form.getByRole('button', { name: 'Reply' })).toHaveAttribute('aria-keyshortcuts', 'Enter')
    const box = form.getByRole('textbox')
    await box.fill('First line.')
    await box.press('Shift+Enter')
    await box.pressSequentially('Second line.')
    await expect(box).toHaveValue('First line.\nSecond line.')
    await box.press('Enter')
    await expect(form.getByRole('status')).toContainText('Recorded message')
    await expect(box).toHaveValue('')
    // toContainText collapses whitespace, so read the text as drawn: the line break must arrive as one.
    const mine = page.getByTestId('conversation').locator('[data-source=operator]').filter({ hasText: 'Second line.' })
    // oxlint-disable-next-line unicorn/prefer-dom-node-text-content -- the text as drawn is the point: a <br> is a line
    await expect.poll(() => mine.innerText()).toContain('First line.\nSecond line.')
})

// One story, so no other test in this file sees the finding gone from the list while it is dismissed.
test("a chore's finding takes a note its next run reads, and is dismissed and listed again", async ({ page }) => {
    await page.goto('attention')
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'lodash-advisory' }).click()
    const detail = page.getByTestId('attention-detail')
    const form = detail.getByRole('form', { name: 'Note' })
    await form.getByRole('textbox').fill('Leave out lodash-advisory until 2026-10-15: the upgrade is merging.')
    await form.getByRole('button', { name: 'Add note' }).click()
    await expect(form.getByRole('status')).toContainText(
        /Recorded message \d+ on chore:deps\. Its next run reads it\./u,
    )
    const mine = detail.getByTestId('conversation').locator('[data-source=operator]').last()
    await expect(mine).toContainText('until 2026-10-15')
    await expect(mine).toContainText('via web')
    await expect(mine).toContainText('waiting for the next run')

    // Dismissed, it leaves the list while the chore still reports it: its row folds away with a leaf drifting off,
    // for the eye alone, and then is gone.
    await detail.getByTestId('dismiss-lodash-advisory').click()
    const list = page.getByTestId('attention-list')
    const leaving = list.locator('li[data-leaving]').filter({ hasText: 'lodash-advisory' })
    await expect(leaving).toHaveCount(1)
    await expect(leaving).toHaveAttribute('aria-hidden', 'true')
    await expect(list.getByRole('link').filter({ hasText: 'lodash-advisory' })).toHaveCount(0)
    await expect(leaving).toHaveCount(0)

    // The chores list counts it apart, as canopy status does, so a chore whose findings are all dismissed reads so.
    await page.goto('chores')
    await expect(page.getByTestId('chore-deps').getByTestId('chore-findings')).toHaveText(
        '0 open findings · 1 dismissed',
    )

    await page.goto('chores/deps')
    await expect(page.getByTestId('chore-notes').locator('[data-source=operator]').last()).toContainText(
        'until 2026-10-15',
    )
    await expect(page.getByTestId('chore-findings-count')).toHaveText('0 · 1 dismissed')
    const finding = page.getByTestId('finding-lodash-advisory')
    await expect(finding).toContainText('dismissed')
    await finding.getByTestId('undismiss-lodash-advisory').click()
    await expect(finding.getByRole('status')).toHaveText(
        'chore:deps lodash-advisory is listed again while the chore reports it.',
    )
    await expect(finding.getByTestId('dismiss-lodash-advisory')).toBeVisible()

    await page.goto('attention')
    await expect(list.getByRole('link').filter({ hasText: 'lodash-advisory' })).toHaveCount(1)

    // Tried last, since its run then starts after the note, which no longer waits for one. The mock starts no
    // process, so the run stays running, and the chore cannot be tried again until it ends.
    await page.goto('chores/deps')
    const actions = page.getByTestId('chore-actions')
    await actions.getByTestId('try-chore').click()
    await expect(actions.getByRole('status')).toContainText(/chore try deps: recorded as chore run \d+, running now\./u)
    await expect(page.getByTestId('chore-runs').locator('li').first()).toContainText('running')
    await expect(actions.getByTestId('try-chore')).toBeDisabled()
})

test('the settings page asks the loop to read its config again and says what it found', async ({ page }) => {
    await page.goto('settings')
    await page.getByTestId('config-reload').click()
    // The mock runs no loop, so its config never changes.
    await expect(page.getByRole('status').filter({ hasText: 'Nothing changed' })).toContainText(
        'the config files say what the loop already runs on.',
    )
})

test('the settings page saves a limit and drops a trusted reviewer, but raises nothing past its ceiling', async ({
    page,
}) => {
    await page.goto('settings')
    await page.getByTestId('limits-open').click()
    await expect(page).toHaveURL(/\/canopy\/settings\/limits$/u)
    const form = page.getByTestId('config-form')
    await expect(form.getByTestId('config-pending')).toHaveText('No unsaved changes')
    const workers = form.getByTestId('capacity.max_workers')
    // The count the mock's fixtures set, whatever it is: the test raises it by one, so it holds when they change.
    await expect(workers).toHaveValue(/^\d+$/u)
    const before = await workers.inputValue()
    const after = String(Number(before) + 1)
    await expect(form.getByTestId('config-save')).toBeDisabled()

    await workers.fill(after)
    await expect(form.getByTestId('config-pending')).toHaveText('1 unsaved change')
    await form.getByTestId('config-discard').click()
    await expect(workers).toHaveValue(before)
    // A choice moves only toward stricter: one looser than the value in force is not offered, and picking the value
    // back leaves nothing to save.
    await expect(form.getByTestId('policy.planner_may_approve-lenient')).toBeDisabled()
    await form.getByTestId('policy.plan-approve').click()
    await expect(form.getByTestId('config-pending')).toHaveText('1 unsaved change')
    await form.getByTestId('policy.plan-off').click()
    await expect(form.getByTestId('config-pending')).toHaveText('No unsaved changes')
    await workers.fill('many')
    await expect(form.getByRole('alert')).toHaveText('capacity.max_workers: a whole number')
    await expect(form.getByTestId('config-save')).toBeDisabled()
    await workers.fill('33')
    await form.getByTestId('config-save').click()
    await expect(form.getByRole('alert')).toContainText('refused (past_bound): capacity.max_workers may be at most 32')

    await workers.fill(after)
    await form.getByTestId('trust.trusted_reviewers-lint-bot').click()
    // Only web has a count of its own; api gets one through the repository picker, not a field per repository.
    const slots = form.getByTestId('repo-slots')
    await expect(slots.getByRole('textbox', { name: /^capacity\.repo_slots\./u })).toHaveCount(1)
    const repos = await openRepoPicker(
        slots.getByRole('button', { name: 'Repository to give its own count: pick a repository' }),
    )
    await repos.getByRole('option', { name: 'api' }).click()
    await slots.getByTestId('capacity.repo_slots.api').fill('3')
    await form.getByTestId('config-save').click()
    await expect(form.getByRole('status')).toContainText(
        "Saved capacity.max_workers, capacity.repo_slots, trust.trusted_reviewers to this workspace's config.",
    )
    await expect(slots.getByTestId('capacity.repo_slots.api')).toHaveValue('3')
    // Read again from the file: the reviewer is gone, and only the stricter side of a trust switch is offered.
    await expect(workers).toHaveValue(after)
    await expect(form.getByTestId('trust.trusted_reviewers-lint-bot')).toHaveCount(0)
    await expect(form.getByTestId('trust.trusted_reviewers-canopy:review')).toBeChecked()
    await expect(form.getByTestId('trust.rebase')).toBeDisabled()
    await expect(form.getByTestId('trust.commit_trailer')).toBeDisabled()
})

test('under Ctrl+Enter, Enter starts a new line and Ctrl+Enter sends', async ({ page }) => {
    await page.goto('settings')
    await page.getByTestId('send-key-mod-enter').click()
    await expect(page.getByTestId('send-key-mod-enter')).toHaveAttribute('aria-checked', 'true')
    // Pressing the key that is on keeps it on: one is always picked.
    await page.getByTestId('send-key-mod-enter').click()
    await expect(page.getByTestId('send-key-mod-enter')).toHaveAttribute('aria-checked', 'true')
    await page.goto('tickets/ABC-101')
    const form = page.getByRole('form', { name: 'Reply' })
    // Chromium on Linux: the button names Ctrl, not ⌘.
    await expect(form.getByRole('button', { name: 'Reply' })).toHaveAttribute('aria-keyshortcuts', 'Control+Enter')
    const box = form.getByRole('textbox')
    await box.fill('One.')
    await box.press('Enter')
    await box.pressSequentially('Two.')
    await expect(box).toHaveValue('One.\nTwo.')
    await box.press('ControlOrMeta+Enter')
    await expect(form.getByRole('status')).toContainText('Recorded message')
    await expect(box).toHaveValue('')
})

test('stop now asks once more, then ends the run', async ({ page }) => {
    await page.goto('tickets/ABC-104')
    await page.getByRole('button', { name: 'Stop now' }).click()
    await page.getByRole('button', { name: 'End run 43 now' }).click()
    await expect(page.getByRole('status')).toContainText('Run 43 was ended and its slots returned.')
    await expect(page.getByTestId('run-43')).toContainText('stopped')
    await expect(page.getByRole('button', { name: 'Start again' })).toBeVisible()
})

test('forget asks for the key typed out, then forgets the branch and PR', async ({ page }) => {
    await page.goto('tickets/ABC-103')
    await page.getByRole('button', { name: 'Forget' }).click()
    const challenge = page.getByRole('form', { name: 'Forget' })
    const forget = challenge.getByRole('button', { name: 'Forget ABC-103' })
    await expect(forget).toBeDisabled()
    await challenge.getByLabel('Type ABC-103 to confirm').fill('ABC-10')
    await expect(forget).toBeDisabled()
    await challenge.getByLabel('Type ABC-103 to confirm').fill('ABC-103')
    await forget.click()
    await expect(page.getByRole('status')).toContainText(
        'ABC-103 is forgotten: its next implement starts over on a new branch. canopy no longer tracks branch ' +
            'agent/ABC-103-billing-v2, https://github.com/acme/web/pull/91.',
    )
    await expect(challenge).toHaveCount(0)
    await expect(page.locator('dt:text-is("branch") + dd')).toHaveText('none')
    // Its conversation reads as the loop's does now: what came before folds away, kept for the asking.
    const thread = page.getByTestId('ticket-conversation')
    const earlier = thread.getByText('Remove it: the mobile app moved to v2 last week.')
    await expect(thread.getByText(/^no messages since its work was forgotten/u)).toBeVisible()
    // The forget heads them, with the branch and PR it dropped, which are yours to delete and close.
    await expect(thread.getByTestId('forgotten')).toContainText('dropped branch agent/ABC-103-billing-v2, acme/web#91')
    await expect(thread.getByRole('link', { name: 'acme/web#91', exact: true })).toBeVisible()
    await expect(earlier).toHaveCount(0)
    await thread.getByRole('button', { name: 'Show 6 earlier messages' }).click()
    await expect(earlier).toBeVisible()
})

test('starting a ticket from the list opens it, private', async ({ page }) => {
    await page.goto('tickets')
    await page.getByLabel('Ticket key').fill('ABC-200')
    await page.getByRole('button', { name: 'Start privately' }).click()
    await expect(page).toHaveURL(/\/canopy\/tickets\/ABC-200$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('ABC-200')
    await expect(page.locator('header').getByText('private', { exact: true })).toBeVisible()
})

test('T opens Start a ticket from any page, which starts it and lands on its page', async ({ page }) => {
    await page.goto('workspace/runs')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Runs')
    await page.keyboard.press('t')
    const dialog = page.getByRole('dialog', { name: 'Start a ticket' })
    await expect(dialog.getByLabel('Ticket key')).toBeFocused()
    await page.keyboard.type('ABC-201')
    await page.keyboard.press('Enter')
    await expect(dialog).toBeHidden()
    await expect(page).toHaveURL(/\/canopy\/tickets\/ABC-201$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('ABC-201')
})

test("Start a ticket plans it first and sets its agents' personas and models, as the ticket's overrides", async ({
    page,
}) => {
    await page.goto('workspace/runs')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Runs')
    await page.keyboard.press('t')
    const dialog = page.getByRole('dialog', { name: 'Start a ticket' })
    await dialog.getByLabel('Ticket key').fill('ABC-202')
    await dialog.getByRole('button', { name: 'Show persona and model overrides' }).click()
    await dialog.getByRole('button', { name: 'planner persona: canopy (default)' }).click()
    await page.getByRole('menuitemradio', { name: 'skeptic' }).click()
    await dialog.getByRole('button', { name: 'worker model: default' }).click()
    const list = page.getByRole('listbox', { name: 'Models' })
    const first = list.getByRole('option', { name: /^[\w.-]+\/[\w.:/+-]+ \(default\)$/u }).first()
    const model = ((await first.getAttribute('aria-label')) ?? '').replace(/ \(default\)$/u, '')
    await first.click()
    await expect(dialog.getByRole('button', { name: `worker model: ${model}` })).toBeVisible()
    // The mock's policy.plan is off, so the box starts unchecked; checked, it asks for a plan as `--plan` does.
    const planFirst = dialog.getByRole('checkbox', { name: 'Plan it first' })
    await expect(planFirst).not.toBeChecked()
    await planFirst.check()
    await dialog.getByRole('button', { name: 'Start privately' }).click()
    await expect(dialog).toBeHidden()
    await expect(page).toHaveURL(/\/canopy\/tickets\/ABC-202$/u)
    // The ticket's page shows each pick as its override, the agents left alone on their defaults.
    const agents = page.getByTestId('ticket-agents')
    await expect(agents.getByRole('button', { name: 'planner persona: skeptic' })).toBeVisible()
    await expect(agents.getByRole('button', { name: 'worker persona: canopy' })).toBeVisible()
    await expect(agents.getByRole('button', { name: `worker model: ${model}` })).toBeVisible()
    await expect(agents.getByRole('button', { name: 'planner model: runtime default' })).toBeVisible()
    const plans = await page.request.get('api/tickets/ABC-202/plans')
    expect(await plans.json()).toMatchObject({ needed: true, setting: 'plan' })
})

test('a refusal names its guard', async ({ page }) => {
    await page.goto('tickets')
    await page.getByLabel('Ticket key').fill('run:4')
    await page.getByRole('button', { name: 'Start privately' }).click()
    await expect(page.getByRole('alert')).toContainText('refused (unsupported)')
})

test('the header pauses the loop and resumes it, as canopy pause and resume do', async ({ page }) => {
    await page.goto('attention')
    const control = page.getByTestId('loop-pause')
    await expect(control).toHaveAttribute('data-paused', 'false')
    await control.getByRole('button', { name: 'Pause' }).click()
    await expect(control).toHaveAttribute('data-paused', 'true')
    await expect(control).toContainText('paused · 0s')
    await expect(control.getByText('paused')).toHaveAttribute('title', /from the web UI$/u)

    // The pause is the journal's: another page reads it back, as the loop does.
    await page.reload()
    await expect(control).toHaveAttribute('data-paused', 'true')
    await control.getByRole('button', { name: 'Resume' }).click()
    await expect(control).toHaveAttribute('data-paused', 'false')
    await expect(control).not.toContainText('paused')
})

test('settings sets a notice to workers, every page shows it, and its banner edits, renews, and clears it', async ({
    page,
}) => {
    await page.goto('settings')
    await expect(page.getByTestId('worker-notice')).toHaveCount(0)
    const set = page.getByTestId('notice-set')
    await expect(set).toBeDisabled()
    await page.getByTestId('notice-text').fill('Artifactory is down: CI builds will likely fail.')
    await page.getByTestId('notice-lasts-1h').click()
    await set.click()
    await expect(page.getByText('Notice set: runs dispatched from now on hear it until it lapses.')).toBeVisible()
    await expect(page.getByTestId('notice-text')).toHaveValue('')
    const banner = page.getByTestId('worker-notice')
    await expect(banner).toContainText('Notice to workers: Artifactory is down: CI builds will likely fail.')
    await expect(banner.getByText(/^Every run dispatched until /u)).toHaveAttribute('title', /from the web UI$/u)

    // The notice is the journal's: another page reads it back, as the next dispatch does.
    await page.goto('workspace/runs')
    await expect(banner).toBeVisible()

    // Edit opens its words in place; saving sets the edited notice in place of the old one.
    await banner.getByRole('button', { name: 'Edit' }).click()
    const words = page.getByTestId('notice-edit-text')
    await expect(words).toHaveValue('Artifactory is down: CI builds will likely fail.')
    await words.fill('Artifactory is back, but slow.')
    await page.getByTestId('notice-edit-set').click()
    await expect(words).toHaveCount(0)
    await expect(banner).toContainText('Notice to workers: Artifactory is back, but slow.')

    // Renew sets it again from now, for the hour it was set for.
    await banner.getByRole('button', { name: 'Renew' }).click()
    await expect(banner).toContainText('Notice to workers: Artifactory is back, but slow.')
    await page.reload()
    await expect(banner).toContainText('Notice to workers: Artifactory is back, but slow.')
    await banner.getByRole('button', { name: 'Clear' }).click()
    await expect(banner).toHaveCount(0)
    await page.reload()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Runs')
    await expect(banner).toHaveCount(0)
})

test('an oversized notice, sent with Enter as a reply is, is refused, naming its guard', async ({ page }) => {
    await page.goto('settings')
    const text = page.getByTestId('notice-text')
    // A blank notice sends nothing, as its disabled button does.
    await text.press('Enter')
    await expect(page.getByRole('alert')).toHaveCount(0)
    await text.fill('x'.repeat(1025))
    await text.press('Enter')
    await expect(page.getByRole('alert')).toContainText('refused (too_long)')
    await expect(page.getByTestId('worker-notice')).toHaveCount(0)
})

test("a review's finding is dismissed on its card for a reason, and kept again", async ({ page }) => {
    await page.goto('pull-requests/reviews/4')
    const card = page.locator('#finding-2')
    await card.getByTestId('dismiss-finding-2').click()
    await page.getByRole('menuitem', { name: /^intentional/u }).click()
    await expect(card.getByRole('status')).toHaveText(
        'review:4 finding 2 is dismissed as intentional: no worker or tick acts on it.',
    )
    await expect(card).toHaveAttribute('data-dismissed', 'true')
    await expect(card).toContainText('dismissed: intentional')
    await card.getByTestId('undismiss-finding-2').click()
    await expect(card).not.toHaveAttribute('data-dismissed', 'true')
    await expect(card.getByTestId('dismiss-finding-2')).toBeVisible()
})

test('a review new to the operator is counted in the nav until its page shows it', async ({ page }) => {
    // The mock operator has seen every review but review 2 (canopy/serve/mock/reviews.py).
    await page.goto('pull-requests/reviews')
    const nav = page.getByRole('navigation', { name: 'Main' })
    await expect(nav.getByRole('link', { name: 'Pull requests 1 new review to read' })).toBeVisible()
    const row = page.getByTestId('review-2')
    await expect(row.getByText('new', { exact: true })).toHaveCount(1)
    await expect(page.getByRole('button', { name: 'mark 1 seen' })).toBeVisible()

    await row.getByRole('link', { name: 'review:2' }).click()
    await expect(page).toHaveURL(/\/pull-requests\/reviews\/2$/u)
    await expect(nav.getByRole('link', { name: 'Pull requests', exact: true })).toBeVisible()

    // Kept in the journal, not the page: it is seen after a reload too.
    await page.goto('pull-requests/reviews')
    await expect(nav.getByRole('link', { name: 'Pull requests', exact: true })).toBeVisible()
    await expect(row.getByText('new', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^mark \d+ seen$/u })).toHaveCount(0)
})

test("a review's findings are sent to a worker from its list, as a reply on its ticket", async ({ page }) => {
    await page.goto('pull-requests/reviews/4')
    const send = page.getByTestId('send-findings')
    await expect(send).toBeDisabled()
    await page.getByTestId('pick-finding-3').click()
    await page.getByTestId('pick-finding-1').click()
    await send.click()
    await expect(page.getByRole('status').filter({ hasText: 'review:4' })).toHaveText(
        /^review:4 findings 1, 3 went to ABC-099 as message \d+: the next tick reads it as your go-ahead\.$/u,
    )
    await expect(send).toBeDisabled()

    // The ticket's conversation has it in the operator's words, naming the findings and never quoting them.
    await page.goto('tickets/ABC-099')
    await expect(page.getByText("Address findings 1 and 3 of canopy's review run 4")).toBeVisible()
})

test("a coworker's PR's review is edited as a draft on its page and published, as canopy review publish does", async ({
    page,
}) => {
    // Review 5, of Carol's PR, is the one review with a draft no other test changes (canopy/serve/mock/reviews.py).
    await page.goto('pull-requests/reviews/5')
    // The page is the draft's record: its title names whose review it is, and its line says where the draft stands.
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('review:5 Your review of acme/api#14 by carol')
    await expect(page.getByTestId('draft-state')).toHaveText('waitingversion 1 · posts nothing until you publish it')
    const draft = page.getByTestId('review-draft')
    await expect(draft.getByTestId('draft-version')).toHaveText('version 1')
    // What canopy's reviewer found is folded under the draft until it is opened.
    const fold = page.getByTestId('reviewer-fold')
    await expect(fold).not.toContainText('summary')
    await fold.getByRole('button', { name: 'Show the review' }).click()
    await expect(fold.getByRole('heading', { name: /^Findings/u })).toBeVisible()
    // Each finding is one card on the diff, the comment it posts as on it: no comment's card beside a finding's.
    const points = page.getByTestId('review-point')
    await expect(points).toHaveCount(3)
    const comments = page.getByTestId('draft-comment')
    await expect(comments).toHaveCount(0)

    // A note asks the next tick for a revision, as canopy reply review:5 does; the mock runs no tick, so it waits.
    const revision = draft.getByTestId('draft-revision')
    await expect(revision).toContainText('0 of 3 revisions')
    const ask = revision.getByRole('form', { name: "Ask for a revision of review run 5's draft" })
    await ask.getByRole('textbox', { name: 'What should change' }).fill('Fold the test finding into comment 1.')
    await ask.getByRole('button', { name: /Ask for a revision/u }).click()
    await expect(revision.getByRole('status')).toHaveText(
        /^Recorded note \d+ on review run 5's draft, at version 1\. The next tick revises it, unless/u,
    )
    await expect(revision).toContainText('Your note asks for a revision: the next tick starts one')
    await expect(revision.getByRole('list', { name: 'Your notes' })).toContainText(
        'Fold the test finding into comment 1.',
    )

    // A version of the operator's own answers the note instead. What the panel says of it is beside the note's.
    const said = draft.getByRole('status').filter({ hasNotText: /^Recorded note/u })
    await draft.getByTestId('draft-body').getByRole('button', { name: 'edit' }).click()
    await draft.getByRole('textbox', { name: 'In your words' }).fill('One thing to fix before this goes in.')
    await draft.getByRole('button', { name: 'Save' }).click()
    await expect(said).toHaveText(/^Review run 5's draft is version 2 now, hash [0-9a-f]{12}: edited the body\.$/u)
    await expect(draft.getByTestId('draft-body')).toContainText('One thing to fix before this goes in.')
    await expect(revision.getByRole('list', { name: 'Your notes' })).toHaveCount(0)
    await expect(revision).toContainText('Tell an agent what to change')

    // A finding's comment is edited in place on its card, and left out and put back with one control.
    const first = points.filter({ hasText: 'The last 503 is returned' })
    await first.getByRole('button', { name: 'Edit' }).click()
    await first.getByRole('textbox', { name: 'In your words' }).fill('Raise once the attempts run out.')
    await first.getByRole('button', { name: 'Save' }).click()
    await expect(first).toContainText('Raise once the attempts run out.')
    const second = points.filter({ hasText: 'is never read' })
    await second.getByRole('button', { name: 'leave out' }).click()
    await page.getByRole('menuitem', { name: /^not worth it/u }).click()
    await expect(second).toContainText('left out')
    // Finding 3 went with the body the operator replaced, which held it: left out, not dismissed.
    await expect(draft.getByTestId('draft-left-out')).toHaveText(
        'Left out: findings 2 and 3. Put one back on its card.',
    )
    await expect(points.filter({ hasText: 'No test stops the backoff' })).toContainText(
        'To have it back, dismiss the finding, then put it back.',
    )
    await second.getByRole('button', { name: 'put back' }).click()
    await expect(second).toContainText('in your review')
    await expect(draft.getByTestId('draft-left-out')).toHaveText('Left out: finding 3. Put one back on its card.')

    // A comment of the operator's own, on any line of the diff, is a card of its own.
    await page.getByRole('button', { name: 'Comment on api/upstream.py:14' }).click()
    const form = page.getByRole('form', { name: 'Comment on api/upstream.py:14' })
    await form.getByRole('textbox', { name: 'In your words' }).fill('Cap the delay?')
    await form.getByRole('button', { name: 'Save' }).click()
    await expect(comments).toHaveCount(1)
    await expect(comments.filter({ hasText: 'Cap the delay?' })).toContainText('yours')
    await expect(draft.getByTestId('draft-version')).toHaveText('version 6')
    await expect(draft.getByTestId('draft-versions')).toContainText('dismissed finding 2')
    await expect(draft.getByTestId('draft-versions')).toContainText('added a comment on api/upstream.py:14')

    // Publish submits it; the outline button beside it would stage it. The mock answers for canopy's GitHub programs:
    // it posts nowhere.
    await expect(draft.getByRole('button', { name: 'Start the review on GitHub' })).toBeVisible()
    await expect(draft.getByTestId('draft-posts')).toContainText('the body and 3 comments as your comment review')
    await expect(draft.getByTestId('draft-posts')).toContainText("on carol's PR, at a61f7c0")
    await draft.getByRole('button', { name: 'Publish version 6' }).click()
    await expect(page.getByTestId('toast')).toContainText("Published version 6 of review run 5's draft")
    await expect(page.getByTestId('toast')).toContainText('https://github.com/acme/api/pull/14#pullrequestreview-')
    await expect(draft.getByTestId('draft-published')).toContainText('Published version 6 as your review on GitHub.')
    // A draft publishes once: nothing on the page changes it now.
    await expect(draft.getByRole('button')).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^Comment on /u })).toHaveCount(0)
    await expect(comments.getByRole('button')).toHaveCount(0)
    // A finding's card keeps only its dismissal, which changes the draft no more.
    await expect(points.getByRole('button', { name: 'Edit' })).toHaveCount(0)
    await expect(points.getByRole('button', { name: 'leave out' })).toHaveCount(0)
})

test('a ticket at its attempt limit is granted one more run from its page, as canopy grant does', async ({ page }) => {
    await page.goto('tickets/ABC-100')
    const limits = page.getByTestId('grant-limits')
    await expect(limits).toContainText('resume in web')
    await expect(limits).toContainText('1 of 1 runs')
    const grant = limits.getByTestId('grant-resume in web')
    // The CLI's command for the same grant is in the text, under the button.
    await expect(limits).toContainText('canopy grant ABC-100 resume --repo web')
    await grant.click()
    await expect(limits.getByRole('status')).toHaveText(
        'ABC-100 in web has had 1 resume runs, and may now have 2. The next tick decides whether to dispatch it.',
    )
    // No longer at its limit, so its row is gone; what the grant did stays said.
    await expect(grant).toHaveCount(0)
})

test("a ticket's worker persona is chosen from its page and cleared, as canopy persona does", async ({ page }) => {
    await page.goto('tickets/ABC-104')
    const personas = page.getByTestId('ticket-agents')
    await expect(personas).toContainText("canopy's default")
    await personas.getByRole('button', { name: 'worker persona: canopy' }).click()
    await page.getByRole('menuitemradio', { name: 'minimalist' }).click()
    await expect(personas.getByRole('status')).toHaveText(
        "ABC-104's worker runs write in minimalist from their next run: this ticket's override.",
    )
    const chosen = personas.getByRole('button', { name: 'worker persona: minimalist' })
    await expect(chosen).toBeVisible()
    await chosen.click()
    await page.getByRole('menuitem', { name: 'Clear the override' }).click()
    await expect(personas.getByRole('status')).toHaveText(
        "ABC-104's worker runs write in canopy from their next run: canopy's default.",
    )
    await expect(personas.getByRole('button', { name: 'worker persona: canopy' })).toBeVisible()
})

test("a ticket's worker model is chosen from its page, among those the runtime lists, and cleared", async ({
    page,
}) => {
    await page.goto('tickets/ABC-104')
    const models = page.getByTestId('ticket-agents')
    const worker = models.getByTestId('ticket-model').first()
    await models.getByRole('button', { name: 'worker model: runtime default' }).click()
    // The mock's runtime lists the models its runs' sessions name, under their providers; the default is pinned
    // above them as a state, not a choice.
    const list = page.getByRole('listbox', { name: 'Models' })
    await expect(list.getByRole('option', { name: 'runtime default nothing sets one' })).toBeDisabled()
    // A model with variants is named at its default; the mock's every model has some.
    const first = list.getByRole('option', { name: /^[\w.-]+\/[\w.:/+-]+ \(default\)$/u }).first()
    const model = ((await first.getAttribute('aria-label')) ?? '').replace(/ \(default\)$/u, '')
    await first.click()
    // Confirmed in the worker's row, in place.
    await expect(worker.getByRole('status')).toHaveText(
        `saved: ABC-104's worker runs use ${model} from their next run: this ticket's override.`,
    )
    const chosen = models.getByRole('button', { name: `worker model: ${model}` })
    await expect(chosen).toBeVisible()
    await expect(worker).toContainText("this ticket's override")
    await chosen.click()
    // Pinned at the top and checked, in a list a field narrows to what is typed.
    await expect(list.getByRole('option', { name: `${model} this ticket's override` })).toHaveAttribute(
        'aria-checked',
        'true',
    )
    // Each model's variants are offered under it, as `canopy model KEY MODEL@VARIANT` takes one.
    await list.getByRole('option', { name: `${model}@high`, exact: true }).click()
    await expect(worker.getByRole('status')).toHaveText(
        `saved: ABC-104's worker runs use ${model}@high from their next run: this ticket's override.`,
    )
    await models.getByRole('button', { name: `worker model: ${model}@high` }).click()
    await page.getByRole('combobox', { name: 'Find a model for the worker' }).fill('no such model')
    await expect(list.getByText('no model has that name')).toBeVisible()
    // Below the list, whatever is typed in it.
    await page.getByRole('button', { name: 'Clear the override' }).click()
    await expect(worker.getByRole('status')).toHaveText(
        "cleared: ABC-104's worker runs use the runtime's default from their next run: nothing sets one.",
    )
    await expect(models.getByRole('button', { name: 'worker model: runtime default' })).toBeVisible()
})

test("a PR at its review limit is granted one more review from its ticket's attention item", async ({ page }) => {
    await page.goto('attention')
    await page.getByTestId('attention-list').getByText('acme/web#88 waits on a reviewer').click()
    const limits = page.getByTestId('attention-detail').getByTestId('grant-limits')
    await expect(limits).toContainText('reviews of acme/web#88')
    await limits.getByTestId('grant-reviews of acme/web#88').click()
    await expect(limits.getByRole('status')).toHaveText(
        'https://github.com/acme/web/pull/88 has had 2 review runs, and may now have 3. ' +
            'The next tick decides whether to review it.',
    )
    await page.goto('pull-requests/pr?url=https%3A%2F%2Fgithub.com%2Facme%2Fweb%2Fpull%2F88')
    await expect(page.getByTestId('pull-request-reviews')).toBeVisible()
    await expect(page.getByTestId('grant-limits')).toHaveCount(0)
})

test("a run's drafted reply is edited and sent from the PR's page, as canopy draft sends it", async ({ page }) => {
    await page.goto('pull-requests/pr?url=https%3A%2F%2Fgithub.com%2Facme%2Fweb%2Fpull%2F88')
    const reply = page.getByTestId('review-thread').filter({ hasText: 'Can it move into a' }).getByTestId('draft')
    await reply.getByRole('button', { name: 'Edit' }).click()
    const text = `Moved it into a finally. ${crypto.randomUUID()}`
    await reply.getByRole('textbox', { name: 'In your words' }).fill(text)
    await reply.getByRole('button', { name: 'Save' }).click()
    await expect(reply.getByRole('status')).toContainText("Run 45's draft 1 is in your words now")
    await expect(reply).toContainText(text)
    await expect(reply.getByText('your text', { exact: true })).toBeVisible()
    // The mock answers for canopy's GitHub programs: the send posts nowhere, and reads as sent.
    await reply.getByRole('button', { name: 'Send' }).click()
    await expect(reply.getByRole('status')).toHaveText(
        /^Sent run 45's draft 1: https:\/\/github\.com\/acme\/web\/pull\/88#discussion_r\d+\.$/u,
    )
    await expect(page.getByTestId('toast')).toContainText("Sent run 45's draft 1")
    await expect(reply).toHaveAttribute('data-status', 'sent')
    await expect(reply.getByRole('button')).toHaveCount(0)
    await expect(reply.getByRole('link', { name: 'The reply on its host' })).toBeVisible()
})

test("a draft's reaction is changed and sent alone from the PR's page, with no reply", async ({ page }) => {
    await page.goto('pull-requests/pr?url=https%3A%2F%2Fgithub.com%2Facme%2Fweb%2Fpull%2F88')
    const nit = page.getByTestId('review-thread').filter({ hasText: 'is type-only' }).getByTestId('draft')
    await expect(nit.getByTestId('draft-reaction')).toContainText('Thumbs up on the comment it answers, alone')
    await nit.getByRole('button', { name: 'Edit' }).click()
    const reactions = nit.getByRole('radiogroup', { name: 'Reaction' })
    await expect(reactions.getByRole('radio', { name: 'Thumbs up' })).toBeChecked()
    await reactions.getByRole('radio', { name: 'Rocket' }).click()
    await nit.getByRole('button', { name: 'Save' }).click()
    await expect(nit.getByRole('status')).toContainText("Run 45's draft 4 is in your words now")
    await expect(nit.getByTestId('draft-reaction')).toContainText('Rocket on the comment it answers, alone')
    await nit.getByRole('button', { name: 'Send' }).click()
    await expect(nit.getByRole('status')).toHaveText(
        /^Sent run 45's draft 4: https:\/\/github\.com\/acme\/web\/pull\/88#discussion_r2468013644\.$/u,
    )
    await expect(nit).toHaveAttribute('data-status', 'sent')
})

test("a stale feedback plan is approved by item from the PR's page, refused once first, as canopy plan does", async ({
    page,
}) => {
    await page.goto('pull-requests/pr?url=https%3A%2F%2Fgithub.com%2Facme%2Fweb%2Fpull%2F88')
    const feedback = page.getByTestId('feedback-plan')
    // carol reviewed the PR after the plan was written; bob's thread carries what the plan proposes for it.
    await expect(feedback.getByTestId('feedback-plan-stale')).toContainText('new review 4102337050 on')
    const bob = page.getByTestId('review-thread').filter({ hasText: 'Why 250?' })
    await expect(bob.getByTestId('plan-proposal')).toContainText('Plan item 3')
    await feedback.getByRole('checkbox', { name: 'approve item 1' }).click()
    const approve = feedback.getByRole('button', { name: 'Approve stale plan' })
    await expect(approve).toHaveAttribute('title', 'canopy plan ABC-099 --approve --leave 1')
    await approve.click()
    // Refused once, as the step it is: a calm note, no error, and the button named for the step after.
    await expect(feedback.getByRole('status')).toContainText('Refused once, as a stale plan is the first time')
    await expect(feedback.getByRole('alert')).toHaveCount(0)
    await expect(feedback.getByTestId('feedback-plan-stale')).toContainText('Approving it again approves it as it is')
    await feedback.getByRole('button', { name: 'Approve as it is' }).click()
    await expect(feedback.getByTestId('plan-approved')).toContainText(
        'Feedback plan 1 of ABC-099 is approved as its file stands now, for 2 of its 3 items: ' +
            'items 2 (id 2468013579) and 3 (id 2468013601).',
    )
    await expect(feedback).toHaveAttribute('data-status', 'approved')
    await expect(feedback.getByRole('checkbox', { name: 'approve item 1' })).not.toBeChecked()
    await expect(feedback.getByTestId('feedback-plan-item').first()).toContainText('for the next plan')
    // At rest, so the send key cannot approve it twice: a box or the words have to change first.
    await expect(feedback.getByRole('button', { name: 'Approve again' })).toBeDisabled()
})

test('a long conversation scrolled away from its end stays put as a message arrives', async ({ page }) => {
    // Thirty copies of its first messages, then any added since, so the reply arrives at the end of a long thread.
    // The first ones kept, and new ones told apart by id: the server sends only the latest 100, so after many runs a
    // reply pushes the oldest out, and neither a count nor what it sends now stays the same.
    let first: { id: number }[] | undefined
    await page.route('**/api/tickets/ABC-103', async (route) => {
        const response = await route.fetch()
        const body = (await response.json()) as { messages: { id: number }[] }
        const seeded = (first ??= body.messages)
        const known = new Set(seeded.map((m) => m.id))
        // Ids past any reply the server will have taken, so a copy never shares one with a real message.
        const padding = Array.from({ length: 30 }, (_, i) => ({ ...seeded[i % seeded.length], id: 1_000_000 + i }))
        body.messages = [...padding, ...body.messages.filter((m) => !known.has(m.id))]
        await route.fulfill({ response, json: body })
    })
    await page.goto('tickets/ABC-103')
    const region = page.getByRole('region', { name: 'Conversation' })
    await expect(page.getByTestId('message-1000029')).toBeAttached()
    // Scrolled as a reader scrolls: the thread hears it on the next frame, so wait for that before anything grows.
    await region.evaluate(async (el) => {
        el.scrollTop = 100
        await new Promise<void>((resolve) => {
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    resolve()
                })
            })
        })
    })
    await expect(region).toHaveJSProperty('scrollTop', 100)
    const form = page.getByRole('form', { name: 'Reply' })
    // Its own text, since the server keeps every reply sent to it: a run before this one may have sent the same.
    const text = `keep my place ${crypto.randomUUID()}`
    await form.getByRole('textbox').fill(text)
    await form.getByRole('button', { name: 'Reply' }).click()
    await expect(page.getByTestId('conversation').getByText(text)).toBeAttached()
    await expect(region).toHaveJSProperty('scrollTop', 100)
    // The reply's `ticket.changed` refetches the ticket, which can still be in the handler when the page closes and
    // disposes its response: drop it, since it comes after everything this test checks.
    await page.unrouteAll({ behavior: 'ignoreErrors' })
})

test("R opens Review a PR from any page, which requests a review and lands on the PR's page", async ({ page }) => {
    const pr = 'https://github.com/acme/web/pull/121'
    await page.goto('workspace/runs')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Runs')
    await page.keyboard.press('r')
    const dialog = page.getByRole('dialog', { name: 'Review a PR' })
    await expect(dialog.getByLabel('PR URL')).toBeFocused()
    await page.keyboard.type(pr)
    await dialog.getByLabel('Notes for the reviewer (optional)').fill('The retry loop is the part that worries me')
    await dialog.getByLabel('Notes for the reviewer (optional)').press('Enter')
    await expect(dialog).toBeHidden()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('acme/web#121')
    const request = page.getByTestId('review-request')
    await expect(request.getByTestId('review-request-notes')).toContainText('The retry loop')

    // On the PR's page, R fills in its URL. One of the loop's own PRs is refused, and the dialog stays open.
    await page.keyboard.press('r')
    await expect(dialog.getByLabel('PR URL')).toHaveValue(pr)
    await dialog.getByLabel('PR URL').fill('https://github.com/acme/web/pull/88')
    await dialog.getByTestId('review-request-submit').click()
    await expect(dialog.getByRole('alert')).toContainText('refused (loop_pr)')
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    // Stopped, so a run of this test again starts from no open request.
    await request.getByTestId('review-request-stop').click()
    await expect(request).toContainText('Your review request ended')
})

test("a coworker's PR is requested from the reviews page and stopped from its own, as the CLI does", async ({
    page,
}) => {
    const pr = 'https://github.com/acme/web/pull/120'
    await page.goto('pull-requests/reviews')
    const form = page.getByTestId('review-request-form')
    // One of the loop's own PRs is refused, as `canopy start URL --review` refuses it.
    await form.getByLabel('PR URL').fill('https://github.com/acme/web/pull/88')
    await form.getByTestId('review-request-submit').click()
    await expect(form.getByRole('alert')).toContainText('refused (loop_pr)')

    // Anything but a PR's URL is said to be one canopy would refuse before it is sent; a PR's names the PR.
    await form.getByLabel('PR URL').fill('https://github.com/acme/web/issues/120')
    await expect(form.getByLabel('PR URL')).toHaveAccessibleDescription("Not a PR's URL, so canopy would refuse it.")
    await form.getByLabel('PR URL').fill(pr)
    await expect(form.getByLabel('PR URL')).toHaveAccessibleDescription('acme/web#120')
    await expect(form.getByTestId('review-request-submit')).toHaveAttribute('title', 'canopy start URL --review')
    // Its review is written in skeptic, as `--persona skeptic` asks: the persona's menu is in the row under the notes.
    await form.getByRole('button', { name: 'Persona: canopy (default)' }).click()
    await expect(page.getByRole('menuitemcheckbox', { name: 'skeptic' })).toHaveAccessibleDescription(
        /^Plans and reviews by naming the input that would break each claim/u,
    )
    await page.getByRole('menuitemcheckbox', { name: 'skeptic' }).click()
    await page.keyboard.press('Escape')
    await expect(form.getByRole('button', { name: 'Persona: skeptic' })).toBeVisible()
    // On a model of its own, as `--model` asks, in place of config's.
    await form.getByRole('button', { name: 'Model: default' }).click()
    await page.getByRole('option', { name: 'anthropic/claude-sonnet-4-5 (default)' }).click()
    await expect(form.getByRole('button', { name: 'Model: anthropic/claude-sonnet-4-5' })).toBeVisible()
    await form.getByTestId('review-request-submit').click()
    // It opens the PR's page, where the request waits on a tick. canopy only reviews it, so it has no ticket's title
    // to lead with.
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('acme/web#120')
    const request = page.getByTestId('review-request')
    await expect(request).toContainText('canopy reviews its head once')
    await expect(request.getByTestId('review-request-personas')).toHaveText(
        'Its review is written in skeptic. Its reviews run on anthropic/claude-sonnet-4-5.',
    )
    // It is in the reviews list, waiting on a tick to start its review, and on the pull requests page too.
    await page.goto('pull-requests/reviews')
    await expect(page.getByTestId('reviews').getByTestId(`requested-${pr}`)).toContainText('requested')
    await page.goto('pull-requests')
    const row = page.getByTestId('pull-requests').getByTestId('pull-request').filter({ hasText: 'acme/web#120' })
    await expect(row).toContainText('requested')

    await row.getByRole('link', { name: 'acme/web#120', exact: true }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('acme/web#120')
    await request.getByTestId('review-request-stop').click()
    await expect(request.getByRole('status')).toHaveText(`${pr}'s review request is stopped; nothing reviews it now.`)
    await expect(request).toContainText('Your review request ended')
    await expect(request.getByTestId('review-request-stop')).toHaveCount(0)
    // Asked again from its page, in the personas the request had, and stopped again.
    await expect(request.getByRole('button', { name: 'Persona: skeptic' })).toBeVisible()
    await request.getByRole('button', { name: 'Review again' }).click()
    await expect(request.getByRole('status')).toHaveText(
        `${pr} is requested for review. The next tick reviews its head, once. Its review is written in skeptic.`,
    )
    await request.getByTestId('review-request-stop').click()
    await expect(request.getByRole('button', { name: 'Review again' })).toBeVisible()
    // Nothing waits on a tick for it any more.
    await page.goto('pull-requests/reviews')
    await expect(page.getByTestId('reviews').getByTestId('review-4')).toBeVisible()
    await expect(page.getByTestId(`requested-${pr}`)).toHaveCount(0)
})

test("a plan's comment is kept, its edit saved and approved, and then the plan skipped, as canopy plan does", async ({
    page,
}) => {
    await page.goto('tickets/ABC-105/plan')
    const actions = page.getByTestId('plan-actions')
    // What an action did shows under it, in the bar at the foot of the plan.
    const said = page.getByTestId('plan-bar').getByRole('status')
    // Where the plan stands: its chip in the Plan panel's header, and the rest in the page's description.
    const panel = page.getByTestId('ticket-plan')
    const state = page.locator('header', { has: page.getByRole('heading', { level: 1 }) })
    await expect(plan(page).getByRole('heading', { level: 3 })).toHaveText('Schedule report exports')

    // An edit is marked unsaved until ⌘S (Ctrl+S) saves it, as a document's is.
    await plan(page).getByText('Exports to anything but CSV.').click()
    await page.keyboard.press('End')
    await page.keyboard.type(' Or PDF.')
    await expect(actions.getByText('Unsaved edits')).toBeVisible()
    await page.keyboard.press('ControlOrMeta+s')
    await expect(said).toContainText('Saved the plan.')
    await expect(actions.getByText('Unsaved edits')).toHaveCount(0)

    // A comment is saved as it is made: it is there when the page is read again.
    await select(page, 'owner_timezone()')
    await page.getByRole('toolbar', { name: 'Format' }).getByRole('button', { name: 'Comment' }).click()
    const form = page.getByRole('form', { name: 'Comment' })
    await form.getByRole('textbox').fill('Which timezone when the owner has none set?')
    await form.getByRole('button', { name: 'Comment' }).click()
    await expect(page.getByRole('article').filter({ hasText: 'owner has none set' })).toBeVisible()
    await expect(actions.getByRole('button', { name: 'Approve' })).toBeEnabled()
    await page.reload()
    await expect(page.getByRole('article').filter({ hasText: 'owner has none set' })).toBeVisible()

    // Ask for changes is a reply: it lands in the ticket's conversation, which its page shows.
    const ask = page.getByRole('form', { name: 'Ask for changes' })
    await ask.getByRole('button', { name: /Ask for changes/u }).click()
    await expect(said).toContainText('the next tick asks the planner for a new plan')
    // A band under the page's header says so until a planner reads it, and another request is asking again.
    await expect(page.getByRole('region', { name: 'Changes asked' })).toContainText('You asked for changes')
    await expect(panel.getByText('changes asked', { exact: true })).toBeVisible()
    await expect(ask.getByRole('button', { name: 'Ask again' })).toBeVisible()

    // An edit, saved and approved in one: the approval takes the file as saved, and its open comments go with it to
    // the implement, as notes, and resolve.
    await plan(page).getByRole('heading', { level: 3 }).click()
    await page.keyboard.press('End')
    await page.keyboard.type(', weekly too')
    await actions.getByRole('button', { name: 'Save and approve with notes' }).click()
    await expect(said).toContainText('Plan 2 of ABC-105 is approved as its file stands now.')
    await expect(said).toContainText('Your notes went with it, to its implement.')
    await expect(page.getByRole('article')).toHaveCount(0)
    await expect(panel).toContainText('approved')
    await expect(state).toContainText('edited since the planner wrote it')

    // Skip asks first, in its place, then supersedes it: no plan waits, and the ticket's own word now says so. What
    // it did stays in the foot, though the plan is read only now and the foot's actions are gone.
    await actions.getByRole('button', { name: 'Skip the plan' }).click()
    await expect(actions.getByText('Skip the plan? Its implement goes ahead without it.')).toBeVisible()
    await actions.getByRole('button', { name: 'Skip the plan' }).click()
    await expect(state).toContainText('Its ticket needs no plan now.')
    await expect(panel).toContainText('superseded')
    await expect(page.getByTestId('plan-actions')).toHaveCount(0)
    await expect(said).toContainText("ABC-105's plan is skipped")

    // The ticket's page has the request in its conversation, and the plan's card says where the plan stands.
    await page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'ABC-105' }).click()
    await expect(page.getByTestId('conversation')).toContainText('Which timezone when the owner has none set?')
    await expect(page.getByTestId('plan-card')).toContainText('superseded')
})

// The mock's lessons are recording (canopy/serve/mock/memory.py): a promoted lesson is served to no run.
test("a proposal is promoted in the operator's words and another rejected from the memory page", async ({ page }) => {
    await page.goto('memory')
    const proposals = page.getByTestId('memory-proposals')
    const proposal = proposals.getByTestId('memory-5')
    await proposal.getByRole('button', { name: 'Edit and promote' }).click()
    const form = proposal.getByRole('form', { name: 'Promote memory:5' })
    await expect(form.getByTestId('promote-replaces')).toHaveText(
        'No lesson is in force under web-tests: it replaces none.',
    )
    await expect(form.getByRole('button', { name: 'Served to runs in: web' })).toBeVisible()
    await form.getByLabel('The lesson, in your words').fill("Run web's tests once, with `npm test -- --run`.")
    await form.getByRole('button', { name: 'Promote memory:5' }).click()
    const said = proposals.getByRole('status')
    await expect(said).toContainText('Proposal 5 is lesson')
    await expect(said).toContainText('It is recorded, not served: memory.proposals is record')
    await expect(proposal).toHaveCount(0)
    const lesson = page.getByTestId('memory-lessons').getByText("Run web's tests once")
    await expect(lesson).toBeVisible()

    await proposals.getByTestId('memory-6').getByRole('button', { name: 'Reject' }).click()
    await expect(said).toHaveText('Proposal 6 is rejected.')
    await expect(proposals.getByTestId('memory-6')).toHaveCount(0)
    await expect(proposals.getByText('all decided: no proposal waits on you')).toBeVisible()
})

test("a ticket's note is forgotten from the memory page, where it shows", async ({ page }) => {
    await page.goto('memory')
    const notes = page.getByTestId('memory-notes')
    const ticket = notes.getByTestId('memory-ticket-ABC-100')
    await ticket.getByRole('button', { name: 'Show 2 notes' }).click()
    const note = ticket.getByTestId('memory-2')
    await note.getByRole('button', { name: 'Forget' }).click()
    const challenge = note.getByRole('form', { name: 'Forget memory:2' })
    await challenge.getByLabel('Type memory:2 to confirm').fill('memory:2')
    await challenge.getByRole('button', { name: 'Forget memory:2' }).click()
    await expect(notes.getByRole('status')).toContainText('Memory 2 (ticket')
    await expect(notes.getByRole('status')).toContainText('is forgotten: its text is deleted.')
    // No longer in force, so its ticket's row lists one note.
    await expect(note).toHaveCount(0)
    await expect(ticket.getByRole('button', { name: 'Hide 1 note' })).toBeVisible()
})

test("a ticket's note is promoted from its page for one repository, and the lesson forgotten", async ({ page }) => {
    await page.goto('tickets/ABC-102')
    const panel = page.getByTestId('ticket-memory')
    await panel.getByRole('button', { name: 'Show 1 note' }).click()
    const note = panel.getByTestId('memory-4')
    await note.getByRole('button', { name: 'Promote' }).click()
    const form = note.getByRole('form', { name: 'Promote memory:4' })
    const repos = await openRepoPicker(form.getByRole('button', { name: 'Served to runs in: every repository' }))
    await expect(repos.getByRole('option', { name: 'every repository' })).toHaveAttribute('aria-checked', 'true')
    await repos.getByRole('option', { name: 'web' }).click()
    await expect(form.getByRole('button', { name: 'Served to runs in: web' })).toBeVisible()
    await form.getByRole('button', { name: 'Promote memory:4' }).click()
    const said = panel.getByRole('status')
    await expect(said).toContainText('Note 4 is lesson')
    await expect(said).toContainText('(export-encoding) for web')
    // The note stays its ticket's.
    await expect(note).toContainText('active')
    const id = /lesson (?<id>\d+)/u.exec((await said.textContent()) ?? '')?.groups?.['id']
    expect(id).toBeDefined()

    await page.goto('memory')
    const lesson = page.getByTestId('memory-lessons').getByTestId(`memory-${id}`)
    await expect(lesson).toContainText('export-encoding')
    await lesson.getByRole('button', { name: 'Forget' }).click()
    const challenge = lesson.getByRole('form', { name: `Forget memory:${id}` })
    const forget = challenge.getByRole('button', { name: `Forget memory:${id}` })
    await expect(forget).toBeDisabled()
    await challenge.getByLabel(`Type memory:${id} to confirm`).fill(`memory:${id}`)
    await forget.click()
    // The mock journal changes as the forget checkpoints, so the status may add that a reader held the log open.
    await expect(page.getByTestId('memory-lessons').getByRole('status')).toContainText(
        `Memory ${id} (lesson export-encoding) is forgotten: its text is deleted.`,
    )
    await expect(lesson).toHaveCount(0)
})

test('a lesson is edited from the memory page, and its versions keep the old words until forgotten', async ({
    page,
}) => {
    await page.goto('memory')
    const lessons = page.getByTestId('memory-lessons')
    const lesson = lessons.getByTestId('memory-8')
    await lesson.hover()
    await lesson.getByRole('button', { name: 'Edit' }).click()
    const form = lesson.getByRole('form', { name: 'Edit memory:8' })
    await form.getByLabel('The lesson, in your words').fill('Billing goes through src/billing/client.ts, v2 included.')
    const repos = await openRepoPicker(form.getByRole('button', { name: 'Served to runs in: web' }))
    await repos.getByRole('option', { name: 'every repository' }).click()
    await form.getByRole('button', { name: 'Edit memory:8' }).click()
    const said = lessons.getByRole('status')
    await expect(said).toContainText('Lesson 8 is edited into lesson')
    await expect(said).toContainText('version 2')
    await expect(said).toContainText('Lesson 8 stays in its history.')
    const id = /into lesson (?<id>\d+)/u.exec((await said.textContent()) ?? '')?.groups?.['id']
    expect(id).toBeDefined()
    await expect(lesson).toHaveCount(0)

    const edited = lessons.getByTestId(`memory-${id}`)
    await expect(edited).toContainText('version 2')
    await expect(edited).toContainText('edited from memory:8')
    await expect(edited).toContainText('from proposal memory:7')
    await edited.getByRole('button', { name: 'Show versions' }).click()
    const versions = edited.getByRole('list', { name: 'Versions, newest first' })
    const old = versions.getByTestId('memory-version-8')
    await expect(old).toContainText('superseded')
    await expect(old).toContainText('Billing goes through src/billing/client.ts alone; the v1 endpoints are gone.')

    // The old words leave the journal from where they show, and the version in force keeps its own.
    await old.getByRole('button', { name: 'Forget' }).click()
    const challenge = old.getByRole('form', { name: 'Forget memory:8' })
    await challenge.getByLabel('Type memory:8 to confirm').fill('memory:8')
    await challenge.getByRole('button', { name: 'Forget memory:8' }).click()
    await expect(said).toContainText('Memory 8 (lesson billing-client) is forgotten: its text is deleted.')
    await expect(old).toContainText('text deleted')
    await expect(edited).toContainText('Billing goes through src/billing/client.ts, v2 included.')
})

test('a task submitted from the tasks page opens its page, and its row arrives on the list', async ({ page }) => {
    await page.goto('tasks')
    const form = page.getByRole('form', { name: 'Submit a task' })
    await expect(form.getByRole('status')).toContainText('opens a draft PR only if your text asks for one')
    // Other tests may submit at the same time, so this task is found by its text.
    const text = `Find out why the nightly export is slow (${test.info().testId}).`
    const picker = await openRepoPicker(form.getByRole('button', { name: /^Runs in: /u }))
    await picker.getByRole('option', { name: 'mobile' }).click()
    await form.getByRole('textbox', { name: 'Task' }).fill(text)
    await form.getByRole('button', { name: /^Submit/u }).click()

    await expect(page.getByText(/^Submitted task:\d+; the next tick starts it\.$/u)).toBeVisible()
    await expect(page).toHaveURL(/\/canopy\/tasks\/\d+$/u)
    const id = /\/tasks\/(\d+)$/u.exec(page.url())?.[1] ?? ''
    await expect(page.getByRole('heading', { level: 1 })).toContainText(`task:${id}`)

    // The list had no row for it when the form sent it: the stream brings it.
    await page.goBack()
    const row = page.getByTestId(`task-${id}`)
    await expect(row).toContainText(text)
    await expect(row).toContainText('mobile')
    await expect(row).toContainText('queued')
    await row.getByRole('link', { name: `task:${id}` }).click()
    await expect(page).toHaveURL(new RegExp(`/canopy/tasks/${id}$`, 'u'))
})

test('a task the server refuses says why, naming its guard, and the form keeps it', async ({ page }) => {
    await page.goto('tasks')
    const form = page.getByRole('form', { name: 'Submit a task' })
    await form.getByRole('textbox', { name: 'Task' }).fill('Plan the offline mode.')
    await form.getByRole('textbox', { name: 'Tracker project' }).fill('not a project')
    await form.getByRole('button', { name: /^Submit/u }).click()
    await expect(form.getByRole('alert')).toContainText('refused (bad_project)')
    await expect(form.getByRole('status')).toHaveCount(0)
    await expect(page).toHaveURL(/\/canopy\/tasks$/u)
    await expect(form.getByRole('textbox', { name: 'Task' })).toHaveValue('Plan the offline mode.')
})

test("a reply answers a task's question, which clears, and its reply shows", async ({ page }) => {
    await page.goto('tasks/4')
    const question = page.getByRole('region', { name: 'A question waiting on you' })
    await expect(question).toBeVisible()
    const form = page.getByRole('form', { name: 'Reply' })
    await form.getByRole('textbox').fill('Yes: rename it in api too.')
    await form.getByRole('button', { name: 'Reply' }).click()
    await expect(form.getByRole('status')).toHaveText(
        /^Recorded message \d+ on task:4, answering message \d+\. The next tick starts its next run, on its branch\.$/u,
    )
    const conversation = page.getByTestId('conversation')
    const mine = conversation.locator('[data-source=operator]').filter({ hasText: 'Yes: rename it in api too.' })
    await expect(mine).toContainText('via web')
    await expect(conversation.getByText('waiting on you')).toHaveCount(0)
    await expect(question).toHaveCount(0)
    // It still takes a reply, now a plain one: the next run reads every one.
    await expect(form.getByRole('textbox', { name: 'Reply', exact: true })).toBeVisible()
})

test("a running run's question waits on you in the list, the rail, and the runs filter, until answered", async ({
    page,
}) => {
    await page.goto('runs?state=blocked')
    // Run 41 runs on, working around its question, and waits on you as well.
    await expect(page.getByTestId('run-41')).toBeVisible()
    await expect(page.getByTestId('rail-run-41')).toContainText('asks you')
    await page.goto('attention')
    const item = page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'run question' })
    await expect(item).toContainText('run:41')
    await expect(item).toContainText('Sign in with SSO')
    await item.click()
    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByTestId('question-line')).toContainText("Waits on your answer to run:41's question")
    const question = detail.getByTestId('attention-question')
    await expect(question).toContainText('Keep the password form beside the SSO button, or hide it behind a link?')
    // The ticket's conversation follows, as a plan's item has it.
    await expect(detail.getByTestId('conversation')).toBeVisible()

    await question.getByRole('button', { name: 'Answer A: keep both side by side' }).click()
    await expect(page.getByTestId('toast')).toContainText('Answered A: keep both side by side.')
    await expect(item).toHaveCount(0)
    await expect(page.getByTestId('rail-run-41')).not.toContainText('asks you')
    await page.goto('runs?state=blocked')
    await expect(page.getByTestId('run-41')).toHaveCount(0)
})

test('stopping a queued task asks once more, then drops it, and its reply goes', async ({ page }) => {
    await page.goto('tasks/7')
    const actions = page.getByTestId('task-actions')
    await actions.getByRole('button', { name: 'Stop', exact: true }).click()
    await actions.getByRole('button', { name: 'Stop task:7' }).click()
    await expect(actions.getByRole('status')).toHaveText(
        'task:7 is stopped; it had not started, and nothing starts it now.',
    )
    await expect(page.getByRole('form', { name: 'Reply' })).toHaveCount(0)
    await expect(page.locator('main header p')).toContainText('stopped')
})

test("stop now ends a task's running run after asking once more", async ({ page }) => {
    await page.goto('tasks/6')
    const actions = page.getByTestId('task-actions')
    await actions.getByRole('button', { name: 'Stop now' }).click()
    await actions.getByRole('button', { name: 'End run 6 now' }).click()
    await expect(actions.getByRole('status')).toHaveText(
        'task:6 is stopped; nothing starts it again. Its run 6 was ended and its slot returned.',
    )
    await expect(page.getByTestId('working-now')).toHaveCount(0)
    await expect(page.getByRole('form', { name: 'Reply' })).toHaveCount(0)
})
