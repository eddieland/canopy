import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("a run's id opens its page, and its transcript opens each tool call to its input and output, as text", async ({
    page,
}) => {
    await page.goto('runs')
    await settled(page)
    await page.getByTestId('run-39').getByRole('link', { name: 'run:39' }).click()
    await expect(page).toHaveURL(/\/runs\/39$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('run:39')
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
    await expect(transcript.locator('input')).toHaveCount(0)
    // Its input is JSON, colored by what each piece is; its output, a file, stays plain.
    await expect(read.locator('.text-syntax-key', { hasText: '"filePath"' })).toBeVisible()
    await expect(output.locator('span')).toHaveCount(0)
    // A failed call shows its error where a call's output goes.
    const missing = tools.filter({ hasText: 'useSearch.ts' }).first()
    await missing.locator('summary').click()
    await expect(missing).toContainText('File not found:')

    await transcript.getByRole('button', { name: 'Open all' }).click()
    await expect(transcript.locator('details[open]')).toHaveCount(7)
    await transcript.getByRole('button', { name: 'Close all' }).click()
    await expect(transcript.locator('details[open]')).toHaveCount(0)

    await page.getByRole('link', { name: 'ABC-099' }).first().click()
    await expect(page).toHaveURL(/\/tickets\/ABC-099$/u)
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
    await first.locator('summary').first().click()
    const sent = first.getByRole('region', { name: 'call 1 input' })
    await expect(sent).toContainText('# canopy worker: implement')
    await expect(sent).toContainText('which no file records')
    const wrote = first.getByRole('region', { name: 'call 1 output' })
    await expect(wrote.getByTestId('transcript-tool')).toHaveCount(3)

    // A later call was sent what the call before it asked its tools for, a failed read's error and a file's markup
    // included, as characters.
    const second = calls.nth(1)
    await second.locator('summary').first().click()
    const returned = second.getByRole('region', { name: 'call 2 input' })
    await expect(returned).toContainText('call 1’s input and output, then what its tools returned:')
    await expect(returned).toContainText('return <input value={query}')
    await expect(returned).toContainText('File not found:')
    await expect(transcript.locator('input')).toHaveCount(0)
    await expect(second.getByRole('region', { name: 'call 2 output' })).toContainText('There is no search hook yet.')

    await transcript.getByRole('button', { name: 'Close all' }).click()
    await expect(transcript.getByTestId('transcript-call-body')).toHaveCount(0)
    await transcript.getByRole('button', { name: 'Open all' }).click()
    await expect(transcript.getByTestId('transcript-call-body')).toHaveCount(3)

    await toggle.click()
    await expect(transcript.getByTestId('transcript-entries')).toBeVisible()
})

test("a failed run's transcript ends in the runtime's error, and a running one's waits for it to end", async ({
    page,
}) => {
    await page.goto('runs/40')
    await settled(page)
    await expect(page.getByTestId('transcript-entries').locator('li').last()).toContainText(
        'APIErrorRate limited: retry after 60s',
    )

    await page.goto('runs/41')
    await settled(page)
    await expect(page.getByTestId('transcript')).toContainText('the session’s events reach the log when it ends')
})

test("a tick's page shows its overseer's session under its decisions", async ({ page }) => {
    await page.goto('ticks/2')
    await settled(page)
    const transcript = page.getByTestId('transcript')
    await expect(transcript).toContainText('session ses_tick2')
    const tools = transcript.getByTestId('transcript-tool')
    await expect(tools).toHaveCount(4)
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

    // A model call opens to its tokens by kind; Open all opens only the tool calls.
    const call = transcript.getByTestId('transcript-step')
    await expect(call).toHaveCount(1)
    const split = call.locator('dl')
    await expect(split).toBeHidden()
    await call.locator('summary').click()
    await expect(split).toHaveText('input2.3kcache read6.5kcache write512output930reasoning310')
    await transcript.getByRole('button', { name: 'Open all' }).click()
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

    await output.getByRole('button', { name: 'Show' }).click()
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

    await output.getByRole('button', { name: 'Hide' }).click()
    await expect(text).toHaveCount(0)

    await page.goto('ticks/1')
    await settled(page)
    await expect(page.getByTestId('tick-output')).toContainText('none kept')
    await expect(page.getByTestId('tick-output').getByRole('button')).toHaveCount(0)
})

test("a tick's output lays its JSON out when asked, and that tick's panel remembers it", async ({ page }) => {
    await page.goto('ticks/2')
    await settled(page)
    const output = page.getByTestId('tick-output')
    await output.getByRole('button', { name: 'Show' }).click()
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
    await output.getByRole('button', { name: 'Show' }).click()
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
    await page.getByTestId('chore-run-2').getByRole('link', { name: '#2' }).click()
    await expect(page).toHaveURL(/\/chores\/deps\/runs\/2$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('chore:deps #2')
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
