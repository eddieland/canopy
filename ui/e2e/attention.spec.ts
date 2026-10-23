import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('the list is most severe first, and the most severe ticket opens beside it', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const rows = page.getByTestId('attention-list').getByRole('link')
    // Broken work, what waits on the operator, the rest by how long it has been open, then a chore's finding.
    await expect(rows).toHaveCount(10)
    const reasons = [
        'worker failed',
        'review waiting',
        'drafts waiting',
        'awaiting reply',
        'plan review',
        'awaiting reply',
        'repo missing',
        'needs reviewer',
        'task ticket unrecorded',
        'lodash-advisory',
    ]
    for (const [index, reason] of reasons.entries()) {
        await expect(rows.nth(index)).toContainText(reason)
    }
    // A reason reads as words, and keeps the CLI's spelling on hover.
    await expect(rows.first().getByTitle('worker_failed')).toHaveText('worker failed')
    // A finding's id is the agent's text: its chip says `finding`, and the id sits beside its chore.
    await expect(rows.nth(9).getByText('finding', { exact: true })).toBeVisible()
    // An item about a ticket names it by its title too; a repository's has none to name.
    await expect(rows.first()).toContainText('Fix the flaky checkout test')
    await expect(rows.nth(6).getByText('untitled')).toHaveCount(0)

    await expect(rows.first()).toHaveAttribute('aria-current', 'page')
    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByRole('link', { name: 'ABC-100', exact: true })).toBeVisible()
    await expect(detail.getByText('Fix the flaky checkout test')).toBeVisible()
})

test("a broken run's item leads with the run, and grants another try without leaving the page", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const detail = page.getByTestId('attention-detail')
    // The run that failed, as the ticket's Runs list shows it: what it said, and its page a click away.
    const run = detail.getByTestId('attention-run')
    await expect(run).toContainText('failed')
    await expect(run.getByRole('link', { name: 'run:40' })).toHaveAttribute('href', /\/runs\/40$/u)
    // The detail's own `run:40` links there too.
    await expect(detail.getByRole('link', { name: 'run:40' })).toHaveCount(2)
    await expect(detail.getByRole('button', { name: 'Allow one more' })).toBeVisible()
    // The run and the grant come before the ticket's own verbs, which sit quietly under the thread.
    const grant = await detail.getByTestId('grant-limits').boundingBox()
    const actions = await detail.getByTestId('attention-actions').boundingBox()
    const first = await run.boundingBox()
    expect(first !== null && grant !== null && actions !== null && first.y < grant.y && grant.y < actions.y).toBe(true)
    // A public ticket with nothing waiting keeps its box open, saying what a note there is for.
    await expect(detail.getByRole('button', { name: 'Show a note for its next worker' })).toHaveCount(0)
    const field = detail.getByRole('form', { name: 'Reply' }).getByRole('textbox')
    await expect(field).toHaveAttribute('placeholder', /^For its next worker, as an instruction\./u)
    await expect(field).not.toHaveAttribute('placeholder', /untrusted/u)
})

test("replies a run drafted lead to the PR's page, where each waits on its thread", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'drafts waiting' }).click()
    const detail = page.getByTestId('attention-detail')
    await detail.getByTestId('attention-drafts').getByRole('link', { name: 'Read the drafts on acme/web#88' }).click()
    await expect(page).toHaveURL(/\/pull-requests\/pr\?url=/u)
    // Each thread at its line, answered or not, and the review's body above the diff.
    await expect(page.getByTestId('review-thread')).toHaveCount(3)
    await expect(page.getByTestId('pr-drafts').getByTestId('draft')).toHaveCount(1)
    await expect(page.getByTestId('draft').and(page.locator('[data-status=waiting]'))).toHaveCount(4)
    await expect(page.getByRole('button', { name: 'Send 4 waiting' })).toBeVisible()
    // The head lists every draft, and each one's link lands on its card; a reaction sent alone is named by it.
    const list = page.getByTestId('draft-list')
    await expect(list.getByRole('listitem')).toHaveCount(4)
    await expect(list.getByRole('link', { name: 'Thumbs up, alone' })).toBeVisible()
    await list.getByRole('link', { name: /^ABC-099 asks for 250 ms/u }).click()
    await expect(page).toHaveURL(/#draft-\d+-2$/u)
    const card = page.getByTestId('review-thread').filter({ hasText: 'Why 250?' }).getByTestId('draft')
    await expect(card).toBeInViewport()
})

test("a requested review's draft leads to the review's page, where it is read and published", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const row = page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'review waiting' })
    // About a PR no ticket owns, named as the PR, waiting on the operator.
    await expect(row).toContainText('acme/api#14')
    await row.click()
    const detail = page.getByTestId('attention-detail')
    // Asked in two personas, both reviews are done, and it leads to the first's draft.
    await expect(detail).toContainText('review:5 and review:6, which you asked for, are done')
    // Its draft is what it asks for, not the PR's review limit.
    await expect(detail).not.toContainText('Nothing to answer here')
    await detail.getByTestId('attention-review').getByRole('link', { name: 'Read the draft of review:5' }).click()
    await expect(page).toHaveURL(/\/reviews\/5$/u)
    // Its page names the request's other review, the skeptic's, so the operator picks the one to publish.
    const siblings = page.getByTestId('draft-siblings')
    await expect(siblings).toContainText('Also reviewed as skeptic, from the same request at this commit.')
    await siblings.getByRole('link', { name: 'skeptic' }).click()
    await expect(page).toHaveURL(/\/reviews\/6$/u)
    await expect(page.getByTestId('draft-siblings').getByRole('link', { name: 'canopy' })).toBeVisible()
})

test("a task's question is named by its text, and leads to the task's page, where it is answered", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const row = page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'task:4' })
    // Named as the tasks list names it, by its text's first line.
    await expect(row).toContainText('Rename the `billing_v1` feature flag')
    await row.click()
    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByTestId('awaiting-line')).toContainText(/^Waits on your answer to message \d+, asked/u)
    // Its page is the answer, not the CLI's commands in its detail, and it has no ticket's reply form.
    await expect(detail.getByTestId('attention-command')).toHaveCount(0)
    await expect(detail.getByRole('form', { name: 'Reply' })).toHaveCount(0)
    await detail.getByTestId('attention-task').getByRole('link', { name: 'Answer on task:4' }).click()
    await expect(page).toHaveURL(/\/tasks\/4$/u)
})

test("a task's other item opens the task, by the link in its head too", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'task ticket unrecorded' }).click()
    const detail = page.getByTestId('attention-detail')
    await expect(detail).toContainText('Find out why the Android build takes twelve minutes.')
    await expect(detail.getByTestId('attention-task').getByRole('link', { name: 'Open task:5' })).toBeVisible()
    await detail.getByRole('link', { name: 'task:5', exact: true }).click()
    await expect(page).toHaveURL(/\/tasks\/5$/u)
})

test("a PR waiting on a reviewer leads with its link out, the detail's one stop for the PR", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'needs reviewer' }).click()
    const detail = page.getByTestId('attention-detail')
    const action = detail.getByTestId('attention-pull-request').getByRole('link')
    await expect(action).toHaveText('acme/web#88 on GitHub')
    await expect(action).toHaveAttribute('href', 'https://github.com/acme/web/pull/88')
    // The head names the PR as text, so above the conversation the PR is one tab stop.
    const said = detail.getByText('acme/web#88 waits on a reviewer')
    await expect(said).toBeVisible()
    await expect(said.getByRole('link')).toHaveCount(0)
    const head = await said.boundingBox()
    const link = await action.boundingBox()
    const actions = await detail.getByTestId('attention-actions').boundingBox()
    expect(head !== null && link !== null && actions !== null && head.y < link.y && link.y < actions.y).toBe(true)
})

test('choosing an item shows its thread and keeps the choice in the URL', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const list = page.getByTestId('attention-list')
    await list.getByRole('link').filter({ hasText: 'awaiting reply' }).filter({ hasText: 'ABC-102' }).click()

    await expect(page).toHaveURL(/\/attention\?item=/u)
    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByRole('link', { name: 'ABC-102', exact: true })).toBeVisible()
    await expect(detail.getByTestId('message-5')).toContainText('Should the export button be red or blue?')
    await expect(detail.getByText('Reply to message 5')).toBeVisible()
    // The head names the question; the conversation holds it, once, and the form is how to answer it.
    await expect(detail.getByTestId('awaiting-line')).toContainText('Waits on your answer to message 5, asked')
    await expect(detail.getByText('Should the export button be red or blue?')).toHaveCount(1)
    await expect(detail).not.toContainText('canopy reply')

    await page.reload()
    await expect(
        list.getByRole('link').filter({ hasText: 'awaiting reply' }).filter({ hasText: 'ABC-102' }),
    ).toHaveAttribute('aria-current', 'page')
})

test("a chore's finding opens the chore's notes and an open form for another", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'lodash-advisory' }).click()

    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByRole('link', { name: 'chore:deps' })).toBeVisible()
    // The finding as its chore's page has it: its title, then what it says of itself, then its link on its own line.
    const text = detail.getByTestId('finding-text')
    await expect(text).toContainText('lodash 4.17.20 has a prototype pollution advisory')
    await expect(text).toContainText('through an old date picker; 4.17.21 fixes it.')
    await expect(text.getByRole('link')).toHaveAttribute('href', 'https://github.com/advisories/GHSA-35jh-r3h4-6jhm')
    await expect(detail.getByTestId('message-8')).toContainText("Leave out the docs site's lockfile")
    await expect(detail.getByTestId('message-8')).not.toContainText('waiting for the next run')
    await expect(detail.getByRole('form', { name: 'Note' })).toBeVisible()
    await expect(detail.getByRole('form', { name: 'Reply' })).toHaveCount(0)
})

test('an item about no ticket offers the command that fixes it, with nothing to answer', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'repo missing' }).click()

    const detail = page.getByTestId('attention-detail')
    await expect(detail).toContainText('api is in the workspace map but has no clone')
    const command = detail.getByTestId('attention-command')
    await expect(command).toContainText('canopy workspace sync')
    await expect(command.getByRole('button', { name: 'Copy command' })).toBeVisible()
    await expect(command).toContainText('Nothing to answer here')
    await expect(detail.getByRole('form', { name: 'Reply' })).toHaveCount(0)
})

test('the counters show the loop at a glance, and the nav counts the list by severity on every page', async ({
    page,
}) => {
    await page.goto('attention')
    await settled(page)
    // ABC-101's and ABC-104's runs, and task 6's; ABC-102, and task 4, waiting on a reply, and ABC-099's feedback
    // plan on your approval.
    await expect(page.getByTestId('counter-running')).toContainText('3')
    await expect(page.getByTestId('counter-waiting')).toContainText('3')
    await expect(page.getByTestId('counter-waiting')).toContainText('oldest')
    await expect(page.getByTestId('counter-attention')).toContainText('10')
    // The split is the nav's, and what waits on you the counter's value: no line under them says either again.
    await expect(page.getByTestId('counter-attention')).toHaveText('Attention10')
    await expect(page.getByTestId('counter-running')).toHaveText('Running3')
    // Outside the rail and the nav, the page says it once: the counter's label.
    await expect(page.getByRole('main').getByText(/waiting on you/iu)).toHaveCount(1)

    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: /Runs/u }).click()
    await expect(page.getByTestId('nav-attention-failed')).toHaveText('1')
    await expect(page.getByTestId('nav-attention-waiting')).toHaveText('5')
    await expect(page.getByTestId('nav-attention-other')).toHaveText('4')
    // Told apart by color, so said in words too: on hover, and in the link's name.
    await expect(page.getByTestId('nav-attention-count')).toHaveAttribute(
        'title',
        '1 broken, 5 waiting on you, 4 other',
    )
    await expect(
        page
            .getByRole('navigation', { name: 'Main' })
            .getByRole('link', { name: /1 broken, 5 waiting on you, 4 other/u }),
    ).toHaveCount(1)
    await expect(page.getByTestId('counters')).toHaveCount(0)
})

test("a question's item is answered in its reply, with the ticket's own actions a quiet row under it", async ({
    page,
}) => {
    await page.goto('attention')
    await settled(page)
    await page
        .getByTestId('attention-list')
        .getByRole('link')
        .filter({ hasText: 'awaiting reply' })
        .filter({ hasText: 'ABC-102' })
        .click()
    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByRole('button', { name: 'Stop', exact: true })).toBeVisible()
    // Whether the ticket is private is said once, as its page's chip says it, over the conversation it decides.
    await expect(detail.getByText('private', { exact: true })).toBeVisible()
    // The reply is what the item asks for, so the ticket's verbs come after it.
    const actions = await detail.getByTestId('attention-actions').boundingBox()
    const reply = await detail.getByRole('textbox', { name: /^Reply/u }).boundingBox()
    expect(actions !== null && reply !== null && reply.y < actions.y).toBe(true)
    // What is working now is the rail's, on every page; the attention page keeps no list of its own.
    await expect(page.getByTestId('workers')).toHaveCount(0)
})

test("a feedback plan's review waits on you, and links to the plan on its PR's page", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const row = page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'plan review' })
    await row.click()
    // Not a ticket plan's: nothing is answered while it waits, and no plan card stands in for it.
    await expect(row).not.toContainText('answered')
    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByTestId('answered-note')).toHaveCount(0)
    await expect(detail.getByTestId('plan-card')).toHaveCount(0)
    const plan = detail.getByTestId('attention-feedback-plan')
    await expect(plan).toHaveText(
        /^Feedback plan 1 for acme\/web#88 waits on you: 3 items, and its PR has moved on since it was written\./u,
    )
    await plan.getByRole('link', { name: 'Approve it on acme/web#88' }).click()
    await expect(page).toHaveURL(/pull-requests\/pr\?url=.+#feedback-plan$/u)
    await expect(page.locator('#feedback-plan')).toBeVisible()
})

test('from a fresh load, the skip link is the first Tab, and the page is the next', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.keyboard.press('Tab')
    const skip = page.getByRole('link', { name: 'Skip to content' })
    await expect(skip).toBeFocused()
    await expect(skip).toBeInViewport()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('main')).toBeFocused()
    await page.keyboard.press('Tab')
    // The second stop is the page's own, past the header and the rail.
    await expect
        .poll(() => page.evaluate(() => document.querySelector('main')?.contains(document.activeElement)))
        .toBe(true)
})

test("on a question's item, the reply is the first stop after the conversation, and its verbs follow", async ({
    page,
}) => {
    await page.goto('attention')
    await settled(page)
    await page
        .getByTestId('attention-list')
        .getByRole('link')
        .filter({ hasText: 'awaiting reply' })
        .filter({ hasText: 'ABC-102' })
        .click()
    const detail = page.getByTestId('attention-detail')
    const conversation = detail.getByRole('region', { name: 'Conversation' })
    await conversation.focus()
    await tabOutOf(page, conversation)
    await expect(detail.getByRole('textbox', { name: 'Reply to message 5' })).toBeFocused()
    // The send button waits for something to send, so the next stop is the ticket's first verb.
    await page.keyboard.press('Tab')
    await expect(detail.getByTestId('attention-actions').getByRole('button').first()).toBeFocused()
})

test('after a reply, the next item waiting on you is chosen, its row focused, and a toast says what was sent', async ({
    page,
}) => {
    // Recorded as the server records it, without writing to this server's journal.
    await page.route('**/api/tickets/ABC-102/replies', (route) =>
        route.fulfill({ json: { message_id: 12, answers: 5, new: true } }),
    )
    await page.goto('attention')
    await settled(page)
    const list = page.getByTestId('attention-list')
    await list.getByRole('link').filter({ hasText: 'awaiting reply' }).filter({ hasText: 'ABC-102' }).click()
    const box = page.getByTestId('attention-detail').getByRole('textbox', { name: 'Reply to message 5' })
    await box.fill('Blue, to match the toolbar.')
    await box.press('Enter')

    // On from it, then from the top: the review the operator asked for, whose draft waits on them.
    const next = list.getByRole('link').filter({ hasText: 'review waiting' })
    await expect(next).toBeFocused()
    await expect(next).toHaveAttribute('aria-current', 'page')
    await expect(page.getByTestId('attention-detail').getByTestId('attention-review')).toBeVisible()
    await expect(page.getByTestId('toast')).toContainText('Recorded message 12 on ABC-102, answering message 5.')
})

test.describe('on half a monitor', () => {
    test.use({ viewport: { width: 820, height: 900 } })

    test('the list fills the width, and an item opens in its place, its reply in reach', async ({ page }) => {
        // Panels rise into place as a page opens; with motion reduced they rest where they end, so the list's top,
        // measured once, is where it stays.
        await page.emulateMedia({ reducedMotion: 'reduce' })
        await page.goto('attention')
        await settled(page)
        const list = page.getByTestId('attention-list')
        const detail = page.getByTestId('attention-detail')
        await expect(detail).toBeHidden()
        const listBox = await list.boundingBox()
        const counters = await page.getByTestId('counters').boundingBox()
        if (listBox === null || counters === null) {
            throw new Error('the list is not drawn')
        }
        // As wide as the counters above it, within a pixel.
        expect(Math.abs(listBox.width - counters.width)).toBeLessThanOrEqual(1)

        await list.getByRole('link').filter({ hasText: 'awaiting reply' }).filter({ hasText: 'ABC-102' }).click()
        await expect(list).toBeHidden()
        const back = page.getByRole('button', { name: 'Back to the list' })
        // The row went with the list, so the focus goes to the item's first stop, where the list began.
        await expect(back).toBeFocused()
        const backBox = await back.boundingBox()
        expect(Math.abs((backBox?.y ?? Infinity) - listBox.y)).toBeLessThanOrEqual(1)
        // Its reply follows its conversation, with no list to scroll past.
        const reply = detail.getByRole('textbox', { name: 'Reply to message 5' })
        await expect(reply).toBeVisible()
        await detail.getByRole('region', { name: 'Conversation' }).focus()
        await tabOutOf(page, detail.getByRole('region', { name: 'Conversation' }))
        await expect(reply).toBeFocused()

        await back.click()
        await expect(detail).toBeHidden()
        const row = list.getByRole('link').filter({ hasText: 'awaiting reply' }).filter({ hasText: 'ABC-102' })
        await expect(row).toBeFocused()
        await expect(row).toHaveAttribute('aria-current', 'page')
    })

    test('an item linked to opens in place of the list', async ({ page }) => {
        await page.goto('attention')
        await settled(page)
        const row = page
            .getByTestId('attention-list')
            .getByRole('link')
            .filter({ hasText: 'awaiting reply' })
            .filter({ hasText: 'ABC-102' })
        const href = await row.getAttribute('href')
        await page.goto(href ?? 'attention')
        await settled(page)
        await expect(page.getByTestId('attention-list')).toBeHidden()
        await expect(
            page.getByTestId('attention-detail').getByRole('textbox', { name: 'Reply to message 5' }),
        ).toBeInViewport()
    })
})

/** Presses Tab until the focus leaves `region`, which holds at most a few dozen stops. */
async function tabOutOf(page: Page, region: Locator): Promise<void> {
    for (let stop = 0; stop < 50; stop += 1) {
        await page.keyboard.press('Tab')
        if (!(await region.evaluate((el) => el.contains(document.activeElement)))) {
            return
        }
    }
    throw new Error('the focus never left the region')
}
