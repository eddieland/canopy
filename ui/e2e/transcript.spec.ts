import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("a run's id opens its page, and its transcript opens each tool call to its input and output, as text", async ({
    page,
}) => {
    // ABC-099's page, since the runs page shows its latest run, 45.
    await page.goto('tickets/ABC-099')
    await settled(page)
    await page.getByTestId('run-39').getByRole('link', { name: 'run:39' }).click()
    await expect(page).toHaveURL(/\/runs\/39$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('run:39 Debounce search input')
    // Its description is its state; what every run's page shows is the title's help, on hover.
    await expect(page.locator('main header p')).toHaveText('done · implement · ABC-099')
    await expect(page.getByRole('heading', { level: 1 })).toHaveAttribute('title', /^What the worker did/u)
    await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Runs' })).toHaveAttribute(
        'data-status',
        'active',
    )

    const transcript = page.getByTestId('transcript')
    await expect(transcript).toContainText('session ses_mock39')
    await expect(transcript).toContainText('7 tool calls, 1 failed')
    // Only the failure count takes the failure color, not the comma before it.
    await expect(transcript.locator('.text-status-failed', { hasText: 'failed' })).toHaveText('1 failed')
    await expect(transcript).toContainText('3 model calls')
    const tools = transcript.getByTestId('transcript-tool')
    await expect(tools).toHaveCount(7)

    // Closed until clicked; a file's markup is characters on the page, never elements.
    const read = tools.filter({ hasText: 'src/search/SearchBox.tsx' }).first()
    const output = read.getByText('return <input value={query}', { exact: false })
    await expect(output).toBeHidden()
    await read.locator('summary').click()
    await expect(output).toBeVisible()
    await expect(transcript.getByTestId('transcript-entries').locator('input')).toHaveCount(0)
    // Its input is JSON, colored by what each piece is; its output, a file, stays plain.
    await expect(read.locator('.text-syntax-key', { hasText: '"filePath"' })).toBeVisible()
    await expect(output.locator('span')).toHaveCount(0)
    // A failed call shows its error where a call's output goes.
    const missing = tools.filter({ hasText: 'useSearch.ts' }).first()
    await missing.locator('summary').click()
    await expect(missing).toContainText('File not found:')

    // All open is one toggle: on opens every call, off closes them all.
    const allOpen = transcript.getByRole('button', { name: 'All open' })
    await allOpen.click()
    await expect(allOpen).toHaveAttribute('aria-pressed', 'true')
    await expect(transcript.locator('details[open]')).toHaveCount(7)
    await allOpen.click()
    await expect(allOpen).toHaveAttribute('aria-pressed', 'false')
    await expect(transcript.locator('details[open]')).toHaveCount(0)

    await page.getByRole('link', { name: 'ABC-099', exact: true }).first().click()
    await expect(page).toHaveURL(/\/tickets\/ABC-099$/u)
})

test('a search keeps the rows with a line that holds it, marked, and opens the calls it is in', async ({ page }) => {
    await page.goto('runs/39')
    await settled(page)
    const transcript = page.getByTestId('transcript')
    const rows = transcript.getByTestId('transcript-entries').locator(':scope > li')
    const all = await rows.count()
    const find = transcript.getByRole('searchbox', { name: 'Find lines in the transcript' })

    await find.fill('DEBOUNCE')
    // The agent's text twice, and two calls: the test run's output, and the pull request's line and input.
    await expect(transcript.getByTestId('transcript-found')).toHaveText('5 lines, 4 rows')
    await expect(rows).toHaveCount(4)
    await expect(transcript.locator('mark').first()).toHaveText('debounce')
    // A call whose input or output holds the query opens to it, its match marked inside the colored JSON.
    await expect(transcript.locator('details[open]')).toHaveCount(2)
    const pr = rows.filter({ hasText: 'github_create_pull_request' })
    await expect(pr.locator('pre mark')).toHaveText('debounce')
    await expect(pr.locator('pre mark .text-syntax-string')).toHaveText('debounce')
    // All open is on while a search holds what it found open, and turned off it closes them too; a new search opens
    // what it finds again.
    const allOpen = transcript.getByRole('button', { name: 'All open' })
    await expect(allOpen).toHaveAttribute('aria-pressed', 'true')
    await allOpen.click()
    await expect(transcript.locator('details[open]')).toHaveCount(0)
    await find.fill('debounces input')
    await expect(transcript.locator('details[open]')).toHaveCount(1)

    // Characters, never a pattern: a dot matches only a dot.
    await find.fill('push.origin')
    await expect(transcript).toContainText('no line holds “push.origin”')
    await expect(rows).toHaveCount(0)

    await find.press('Escape')
    await expect(find).toHaveValue('')
    await expect(rows).toHaveCount(all)
    await expect(transcript.locator('mark')).toHaveCount(0)
    await expect(transcript.locator('details[open]')).toHaveCount(0)

    // By call keeps its own rows, whole: the search waits for the events in order.
    await find.fill('debounce')
    await transcript.getByRole('button', { name: 'By call' }).click()
    await expect(find).toBeHidden()
    await expect(transcript.getByTestId('transcript-call')).toHaveCount(3)
    await expect(transcript.locator('mark')).toHaveCount(0)
})

test('by call, each model call opens to what it was sent and what it did, as text', async ({ page }) => {
    await page.goto('runs/39')
    await settled(page)
    const transcript = page.getByTestId('transcript')
    const toggle = transcript.getByRole('button', { name: 'By call' })
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-pressed', 'true')
    const calls = transcript.getByTestId('transcript-call')
    await expect(calls).toHaveCount(3)
    // A call's line is what it did: its first text, then its tools by name, counted.
    await expect(calls.nth(0)).toContainText("I'll read the ticket, then the search box. · jira_get_issue, read ×2")
    await expect(calls.nth(2)).toContainText('stop')

    // The first call was sent the prompt canopy kept, and the rest no file records; its body is built when opened.
    const first = calls.nth(0)
    await expect(first.getByTestId('transcript-call-body')).toHaveCount(0)
    await first.locator('[data-slot=collapsible-trigger]').click()
    const sent = first.getByRole('region', { name: 'call 1 input' })
    await expect(sent).toContainText('# canopy worker: implement')
    await expect(sent).toContainText('which no file records')
    const wrote = first.getByRole('region', { name: 'call 1 output' })
    await expect(wrote.getByTestId('transcript-tool')).toHaveCount(3)

    // A later call was sent what the call before it asked its tools for, a failed read's error and a file's markup
    // included, as characters.
    const second = calls.nth(1)
    await second.locator('[data-slot=collapsible-trigger]').click()
    const returned = second.getByRole('region', { name: 'call 2 input' })
    await expect(returned).toContainText('call 1’s input and output, then what its tools returned:')
    await expect(returned).toContainText('return <input value={query}')
    await expect(returned).toContainText('File not found:')
    await expect(transcript.locator('input')).toHaveCount(0)
    await expect(second.getByRole('region', { name: 'call 2 output' })).toContainText('There is no search hook yet.')

    // All open, turned on and off, opens every call and then closes them all, the two opened by hand included.
    const allOpen = transcript.getByRole('button', { name: 'All open' })
    await allOpen.click()
    await expect(transcript.getByTestId('transcript-call-body')).toHaveCount(3)
    await allOpen.click()
    await expect(transcript.getByTestId('transcript-call-body')).toHaveCount(0)
    await allOpen.click()
    await expect(transcript.getByTestId('transcript-call-body')).toHaveCount(3)

    await toggle.click()
    await expect(transcript.getByTestId('transcript-entries')).toBeVisible()
})

test("a failed run's transcript ends in the runtime's error, and a running one's is what it printed so far", async ({
    page,
}) => {
    await page.goto('runs/40')
    await settled(page)
    await expect(page.getByTestId('transcript-entries').locator('li').last()).toContainText(
        'APIErrorRate limited: retry after 60s',
    )

    await page.goto('runs/41')
    await settled(page)
    // Its latest tool call is on its row, and the calls so far in its transcript.
    await expect(page.getByTestId('run-doing')).toContainText('bashnpm test -- login')
    const tools = page.getByTestId('transcript').getByTestId('transcript-tool')
    await expect(tools).toHaveCount(2)
    await expect(tools.last()).toContainText('npm test -- login')
})

test("a transcript's chart names what grew each call's context, and shows the largest addition's row", async ({
    page,
}) => {
    await page.goto('runs/39')
    await settled(page)
    const transcript = page.getByTestId('transcript')
    const context = transcript.getByTestId('transcript-context')
    await expect(context).toContainText('peak 30.2k at call 3')
    // The largest single addition, on the chart's line: the test run's output, a coverage table.
    const largest = context.getByTestId('context-largest')
    await expect(largest).toHaveText('largest additionbashnpm test -- search≈4.2k into call 3')

    // At first the chart picks the call it grew, and lists what grew it, largest first, each its share by characters.
    const calls = context.getByRole('radiogroup', { name: 'Model calls' })
    await expect(calls.getByRole('radio')).toHaveCount(3)
    await expect(calls.getByRole('radio', { name: 'call 3: 30.2k sent, +4.3k on the call before' })).toBeChecked()
    const grew = context.getByTestId('context-grew')
    await expect(grew).toContainText('call 3, 30.2k sent, +4.3k on call 2, from what call 2 printed, largest first:')
    await expect(grew.getByRole('listitem')).toHaveText([
        '≈4.2kbashnpm test -- search',
        '≈62writesrc/search/useSearch.ts',
        "≈34textThere is no search hook yet. I'll add one that debounces and aborts the stale request.",
    ])
    // The first call is canopy's prompt and the runtime's own.
    await calls.getByRole('radio', { name: 'call 1: 24.6k sent' }).click()
    await expect(context).toContainText('call 1, 24.6k sent: ≈176 canopy’s prompt, ≈24.4k the runtime’s own')

    // By call says each call's step on its line.
    const find = transcript.getByRole('searchbox', { name: 'Find lines in the transcript' })
    await find.fill('push')
    await transcript.getByRole('button', { name: 'By call' }).click()
    await expect(transcript.getByTestId('transcript-call').nth(2)).toContainText('30.2k in (+4.3k) · ')

    // One click from the chart shows the row in order, whatever the view and the search: opened, scrolled to, focused.
    await largest.getByRole('button').click()
    await expect(transcript.getByRole('button', { name: 'By call' })).toHaveAttribute('aria-pressed', 'false')
    await expect(find).toHaveValue('')
    const run = transcript.getByTestId('transcript-tool').filter({ hasText: 'npm test -- search' })
    await expect(run.locator('details')).toHaveAttribute('open', '')
    await expect(run).toContainText('src/search/query.ts')
    await expect(run.locator('summary')).toBeFocused()
    await expect(run.locator('summary')).toBeInViewport()
    await expect(transcript.locator('details[open]')).toHaveCount(1)
})

test("a session of one model call has its context's line, and no bars", async ({ page }) => {
    await page.goto('ticks/2')
    await settled(page)
    const context = page.getByTestId('transcript-context')
    await expect(context).toContainText('call 1, 9.3k sent: ≈84 canopy’s prompt, ≈9.2k the runtime’s own')
    await expect(context.getByRole('radio')).toHaveCount(0)
})

test("a tick's page shows its overseer's session under its decisions", async ({ page }) => {
    await page.goto('ticks/2')
    await settled(page)
    const transcript = page.getByTestId('transcript')
    const tools = transcript.getByTestId('transcript-tool')
    await expect(tools).toHaveCount(4)
    // Its session is named once, in the Tick panel's overseer field, not again over the transcript.
    await expect(page.locator('main')).toContainText('session ses_tick2')
    await expect(transcript).not.toContainText('session ses_tick2')
    await expect(transcript).toContainText('4 tool calls, 1 refused')

    // A shell call's line is its command, with what it printed when that is one short line.
    const decide = tools.filter({ hasText: "canopy decide ABC-101 wait 'run 41 is implementing it.'" })
    await expect(decide).toContainText('recorded decision 8')
    // An untitled call's line is its input's short values.
    await expect(tools.nth(1)).toContainText('method=get_status owner=acme repo=web pullNumber=88')
    // canopy's refusal is marked so, though the runtime says the call completed.
    const dispatch = tools.filter({ hasText: 'canopy dispatch ABC-104' })
    await expect(dispatch).toContainText('refused: running')
    await expect(dispatch).toContainText('dispatch refused (running): run 43 is still working ABC-104')

    // JSON output opens indented.
    await tools.nth(1).locator('summary').click()
    await expect(tools.nth(1).locator('pre').last()).toContainText('{\n  "state": "pending",')

    // A model call's line says what it was sent and wrote, as By call does; it opens to its tokens by kind and to
    // what By call shows of it, its body built only once opened, and All open opens only the tool calls.
    const call = transcript.getByTestId('transcript-step')
    await expect(call).toHaveCount(1)
    await expect(call.locator('summary').first()).toContainText('model call 1')
    await expect(call.locator('summary').first()).toContainText('9.3k in · 1.2k out')
    const split = call.locator('dl')
    await expect(call.getByTestId('transcript-call-body')).toHaveCount(0)
    await call.locator('summary').first().click()
    await expect(split).toHaveText('input2.3kcache read6.5kcache write512output930reasoning310')
    await expect(call.getByRole('region', { name: 'call 1 input' })).toContainText('which no file records')
    await expect(call.getByRole('region', { name: 'call 1 output' }).getByTestId('transcript-tool')).toHaveCount(4)
    await transcript.getByRole('button', { name: 'All open' }).click()
    await expect(transcript.locator('details[open]')).toHaveCount(4)
    await expect(split).toBeHidden()
})

test("a tick's output shows as written when asked, stderr included, and a tick that kept none says so", async ({
    page,
}) => {
    await page.goto('ticks/2')
    await settled(page)
    const output = page.getByTestId('tick-output')
    await expect(output).toContainText('.canopy/ticks/2.log as written: stdout, then stderr')
    const text = output.getByTestId('tick-output-text')
    await expect(text).toHaveCount(0)

    await output.getByRole('button', { name: 'Show output' }).click()
    await expect(text).toContainText('--- stderr ---')
    await expect(text).toContainText('service=mcp key=jira error=timed out after 1000ms listing prompts')
    // The session's events too, as the runtime printed them: lines of JSON, as text.
    await expect(text).toContainText('"sessionID": "ses_tick2"')
    // Colored by what each piece is, while a line that is not JSON stays plain.
    await expect(text.locator('.text-syntax-key', { hasText: '"sessionID"' }).first()).toBeVisible()
    await expect(text.locator('.text-syntax-string', { hasText: '"ses_tick2"' }).first()).toBeVisible()
    await expect(text.locator('span', { hasText: 'service=mcp' })).toHaveCount(0)
    // The file's size, in the header.
    await expect(output).toContainText(/\d+\.\d KiB/u)
    // It opens at its end, where stderr is.
    await expect.poll(() => text.evaluate((el) => el.scrollTop + el.clientHeight >= el.scrollHeight - 1)).toBe(true)

    await output.getByRole('button', { name: 'Hide output' }).click()
    await expect(text).toHaveCount(0)

    await page.goto('ticks/1')
    await settled(page)
    await expect(page.getByTestId('tick-output')).toContainText('no output kept')
    await expect(page.getByTestId('tick-output').getByRole('button')).toHaveCount(0)
})

test("a tick's output lays its JSON out when asked, and that tick's panel remembers it", async ({ page }) => {
    await page.goto('ticks/2')
    await settled(page)
    const output = page.getByTestId('tick-output')
    await output.getByRole('button', { name: 'Show output' }).click()
    const text = output.getByTestId('tick-output-text')
    const pretty = output.getByRole('button', { name: 'Pretty' })
    const read = () => text.evaluate((el) => el.textContent)
    await expect(pretty).toHaveAttribute('aria-pressed', 'false')
    expect(await read()).toContain('{"type": "text", "timestamp"')

    await pretty.click()
    await expect(pretty).toHaveAttribute('aria-pressed', 'true')
    expect(await read()).toContain('{\n  "type": "text",\n  "timestamp"')
    // It opens at its end again, where stderr is: every line moved.
    await expect.poll(() => text.evaluate((el) => el.scrollTop + el.clientHeight >= el.scrollHeight - 1)).toBe(true)
    // A line that is not JSON stays as it was.
    expect(await read()).toContain('\n--- stderr ---\n')
    // Still colored.
    await expect(text.locator('.text-syntax-key', { hasText: '"sessionID"' }).first()).toBeVisible()

    // Kept for this tick across a reload.
    expect(await page.evaluate(() => globalThis.localStorage.getItem('canopy-pretty-output'))).toBe('[2]')
    await page.reload()
    await settled(page)
    await output.getByRole('button', { name: 'Show output' }).click()
    await expect(pretty).toHaveAttribute('aria-pressed', 'true')
    expect(await read()).toContain('{\n  "type": "text",')

    await pretty.click()
    await expect(pretty).toHaveAttribute('aria-pressed', 'false')
    expect(await read()).toContain('{"type": "text", "timestamp"')
    expect(await page.evaluate(() => globalThis.localStorage.getItem('canopy-pretty-output'))).toBe('[]')
})

test("a chore run's id opens its page: what it reported, in full, over its session's transcript", async ({ page }) => {
    await page.goto('chores/deps')
    await settled(page)
    await page.getByTestId('chore-run-2').getByRole('link', { name: 'chore:deps#2' }).click()
    await expect(page).toHaveURL(/\/chores\/deps\/runs\/2$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('chore:deps#2')
    await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Chores' })).toHaveAttribute(
        'data-status',
        'active',
    )
    await expect(page.getByTestId('chore-run-findings')).toContainText('lodash 4.17.20 has a prototype pollution')

    const transcript = page.getByTestId('transcript')
    await expect(transcript).toContainText('session ses_chore2')
    const tools = transcript.getByTestId('transcript-tool')
    await expect(tools).toHaveCount(2)
    const web = tools.filter({ hasText: "Audit web's dependencies" })
    await web.locator('summary').click()
    await expect(web).toContainText('1 high severity vulnerability')

    await page.locator('dl').getByRole('link', { name: 'chore:deps' }).click()
    await expect(page).toHaveURL(/\/chores\/deps$/u)

    await page.goto('chores/build-health/runs/4')
    await settled(page)
    await expect(page.getByTestId('transcript')).toContainText('the session’s events reach the log when it ends')
    await page.goto('chores/deps/runs/4')
    await expect(page.getByText("chore 'deps' has no run 4")).toBeVisible()
})

test('a run that does not exist, or a path that names none, says so', async ({ page }) => {
    await page.goto('runs/99')
    await expect(page.getByText('no run 99')).toBeVisible()
    await page.goto('runs/two')
    await expect(page.getByText("not a run: a run's id is a positive number")).toBeVisible()
})
