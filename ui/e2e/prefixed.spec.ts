import { expect, test } from '@playwright/test'

// Served under /canopy, signing nobody in, with the mock journal changing every 250 ms (playwright.config.ts). The
// writes happen here, not on the root server, whose screenshots need its journal as seeded.

test('the app works under a path prefix', async ({ page }) => {
    await page.goto('')
    await expect(page).toHaveURL(/\/canopy\/attention$/u)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Runs' }).click()
    await expect(page).toHaveURL(/\/canopy\/runs$/u)
    await page.reload()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Runs')
})

test('stream events update the cache without refetching', async ({ page }) => {
    const fetches: string[] = []
    page.on('request', (request) => {
        if (request.resourceType() === 'fetch') {
            fetches.push(new URL(request.url()).pathname)
        }
    })
    await page.goto('runs')
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
    const item = page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'awaiting reply' })
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
    // toContainText collapses whitespace, so read the text itself: the line break must arrive as one.
    const mine = page.getByTestId('conversation').locator('[data-source=operator]').filter({ hasText: 'Second line.' })
    await expect.poll(() => mine.textContent()).toContain('First line.\nSecond line.')
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
})

test('the settings page asks the loop to read its config again and says what it found', async ({ page }) => {
    await page.goto('settings')
    await page.getByTestId('config-reload').click()
    // The mock runs no loop, so its config never changes.
    await expect(page.getByRole('status').filter({ hasText: 'Nothing changed' })).toContainText(
        'the config files say what the loop already runs on.',
    )
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
})

test('starting a ticket from the list opens it, private', async ({ page }) => {
    await page.goto('tickets')
    await page.getByLabel('Ticket key').fill('ABC-200')
    await page.getByRole('button', { name: 'Start privately' }).click()
    await expect(page).toHaveURL(/\/canopy\/tickets\/ABC-200$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('ABC-200')
    await expect(page.locator('header').getByText('private', { exact: true })).toBeVisible()
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

test('settings sets a notice to workers, every page shows it, and its banner clears it', async ({ page }) => {
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
    await page.goto('runs')
    await expect(banner).toBeVisible()
    await banner.getByRole('button', { name: 'Clear' }).click()
    await expect(banner).toHaveCount(0)
    await page.reload()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Runs')
    await expect(banner).toHaveCount(0)
})

test('an oversized notice is refused, naming its guard', async ({ page }) => {
    await page.goto('settings')
    await page.getByTestId('notice-text').fill('x'.repeat(1025))
    await page.getByTestId('notice-set').click()
    await expect(page.getByRole('alert')).toContainText('refused (too_long)')
    await expect(page.getByTestId('worker-notice')).toHaveCount(0)
})

test("a review's finding is dismissed on its card, and kept again", async ({ page }) => {
    await page.goto('reviews/4')
    const card = page.locator('#finding-2')
    await card.getByTestId('dismiss-finding-2').click()
    await expect(card.getByRole('status')).toHaveText('review:4 finding 2 is dismissed: no worker or tick acts on it.')
    await expect(card).toHaveAttribute('data-dismissed', 'true')
    await card.getByTestId('undismiss-finding-2').click()
    await expect(card).not.toHaveAttribute('data-dismissed', 'true')
    await expect(card.getByTestId('dismiss-finding-2')).toBeVisible()
})

test("a review's findings are sent to a worker from its list, as a reply on its ticket", async ({ page }) => {
    await page.goto('reviews/4')
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

test('a ticket at its attempt limit is granted one more run from its page, as canopy grant does', async ({ page }) => {
    await page.goto('tickets/ABC-100')
    const limits = page.getByTestId('grant-limits')
    await expect(limits).toContainText('fix-ci in web')
    await expect(limits).toContainText('1 of 1 runs')
    const grant = limits.getByTestId('grant-fix-ci in web')
    await expect(grant).toHaveAttribute('title', 'canopy grant ABC-100 fix-ci --repo web')
    await grant.click()
    await expect(limits.getByRole('status')).toHaveText(
        'ABC-100 in web has had 1 fix-ci runs, and may now have 2. The next tick decides whether to dispatch it.',
    )
    // No longer at its limit, so its row is gone; what the grant did stays said.
    await expect(grant).toHaveCount(0)
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

test("a coworker's PR is requested from the pull requests page and stopped from its own, as the CLI does", async ({
    page,
}) => {
    const pr = 'https://github.com/acme/web/pull/120'
    await page.goto('pull-requests')
    const form = page.getByTestId('review-request-form')
    // One of the loop's own PRs is refused, as `canopy start URL --review` refuses it.
    await form.getByLabel('PR URL').fill('https://github.com/acme/web/pull/88')
    await form.getByTestId('review-request-submit').click()
    await expect(form.getByRole('alert')).toContainText('refused (loop_pr)')

    await form.getByLabel('PR URL').fill(pr)
    await expect(form.getByTestId('review-request-submit')).toHaveAttribute('title', 'canopy start URL --review')
    await form.getByTestId('review-request-submit').click()
    await expect(form.getByRole('status')).toHaveText(
        `${pr} is requested for review. The next tick reviews its head, once.`,
    )
    const row = page.getByTestId('pull-requests').getByTestId('pull-request').filter({ hasText: 'acme/web#120' })
    await expect(row).toContainText('requested')

    await row.getByRole('link', { name: 'acme/web#120', exact: true }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('acme/web#120')
    const request = page.getByTestId('review-request')
    await expect(request).toContainText('canopy reviews its head once')
    await request.getByTestId('review-request-stop').click()
    await expect(request.getByRole('status')).toHaveText(`${pr}'s review request is stopped; nothing reviews it now.`)
    await expect(request).toContainText('Your review request ended')
    await expect(request.getByTestId('review-request-stop')).toHaveCount(0)
})
