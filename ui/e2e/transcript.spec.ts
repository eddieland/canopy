import { expect, test } from '@playwright/test'
import type { Locator } from '@playwright/test'

import { FULL_RAIL, settled, signIn, windowWidth } from './helpers.ts'

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

    // By call searches too: it keeps the calls with a line that holds the query, each opened to it, marked.
    await find.fill('debounce')
    await transcript.getByRole('button', { name: 'By call' }).click()
    await expect(find).toBeVisible()
    await expect(transcript.getByTestId('transcript-found')).toContainText(/ calls?$/u)
    const calls = transcript.getByTestId('transcript-call')
    await expect(calls.first().getByTestId('transcript-call-body')).toBeVisible()
    await expect(calls.first().locator('mark').first()).toHaveText(/^debounce$/iu)
    await find.fill('push.origin')
    await expect(transcript).toContainText('no call holds “push.origin”')
    await find.press('Escape')
    await expect(calls).toHaveCount(3)
})

test('f puts the focus in the transcript’s search from anywhere on the page, in order and By call', async ({
    page,
}) => {
    await page.goto('runs/39')
    await settled(page)
    const transcript = page.getByTestId('transcript')
    const find = transcript.getByRole('searchbox', { name: 'Find lines in the transcript' })
    await page.getByRole('main').focus()
    await page.keyboard.press('f')
    await expect(find).toBeFocused()
    // Typed into the field, f is a letter.
    await page.keyboard.press('f')
    await expect(find).toHaveValue('f')
    await find.press('Escape')

    await transcript.getByRole('button', { name: 'By call' }).click()
    await page.getByRole('main').focus()
    await page.keyboard.press('f')
    await expect(find).toBeFocused()
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
    await expect(transcript.getByTestId('transcript-calls').locator('input')).toHaveCount(0)
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

test("a failed run's Run panel names the error it ended on, and a running one's transcript is so far", async ({
    page,
}) => {
    await page.goto('runs/40')
    await settled(page)
    const last = page.getByTestId('transcript-entries').locator('li').last()
    await expect(last).toContainText('APIErrorRate limited: retry after 60s')
    // Its Run panel names what it ended on, above the transcript, and shows that row on a click.
    const endedOn = page.getByRole('button', { name: '+3:54 APIError Rate limited: retry after 60s' })
    await expect(endedOn).toBeVisible()
    await page.getByRole('searchbox', { name: 'Find lines in the transcript' }).fill('gh run')
    await expect(last).not.toContainText('APIError')
    await endedOn.click()
    await expect(last).toContainText('APIErrorRate limited: retry after 60s')
    await expect(last).toBeFocused()
    await expect(last).toBeInViewport()

    // A run that ended done names nothing.
    await page.goto('runs/39')
    await settled(page)
    await expect(page.getByText('ended on')).toHaveCount(0)

    await page.goto('runs/41')
    await settled(page)
    // Its latest tool call is on its row, and the calls so far in its transcript.
    await expect(page.getByTestId('run-doing')).toContainText('bashnpm test -- login')
    const tools = page.getByTestId('transcript').getByTestId('transcript-tool')
    await expect(tools).toHaveCount(2)
    await expect(tools.last()).toContainText('npm test -- login')
})

test("a run's output is its log as written: what its setup commands and the runtime printed, read when shown", async ({
    page,
}) => {
    await page.goto('runs/40')
    await settled(page)
    const output = page.getByTestId('run-output')
    await expect(output).toContainText('the run’s log as written: its setup commands’ output')
    await expect(output.getByTestId('run-output-text')).toHaveCount(0)

    await output.getByRole('button', { name: 'Show output' }).click()
    const text = output.getByTestId('run-output-text')
    await expect(text).toContainText('--- setup web stdout ---')
    await expect(text).toContainText('Packages: +412')
    await expect(text).toContainText('error=rate limited: retry after 30s')
    await expect(text).toContainText('--- worker exit 1 ---')
    // None of which is the session's: the transcript leaves it out.
    await expect(page.getByTestId('transcript-entries')).not.toContainText('Packages: +412')
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

    // Opened, the chart picks the call it grew, and lists what grew it, largest first, each its share by characters.
    await context.getByRole('button', { name: 'Show chart' }).click()
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
    await transcript.getByRole('button', { name: 'By call' }).click()
    await expect(transcript.getByTestId('transcript-call').nth(2)).toContainText('30.2k in (+4.3k) · ')
    await find.fill('push')

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

/** The middle of an element's box across the page, or NaN for one not drawn, which no comparison passes. */
function center(box: { x: number; width: number } | null): number {
    return box === null ? Number.NaN : box.x + box.width / 2
}

test("a short session's context bars stand centered in their track, each call's number under its bar", async ({
    page,
}) => {
    await page.goto('runs/39')
    await settled(page)
    const context = page.getByTestId('transcript-context')
    await context.getByRole('button', { name: 'Show chart' }).click()
    const plot = context.getByTestId('context-plot')
    await expect(plot.getByRole('radio')).toHaveCount(3)
    const track = await plot.boundingBox()
    const first = await context.getByTestId('context-call-1').boundingBox()
    const last = await context.getByTestId('context-call-3').boundingBox()
    // Three bars, not a clump at the track's left: the row's middle is the track's.
    const row = { x: first?.x ?? 0, width: (last?.x ?? 0) + (last?.width ?? 0) - (first?.x ?? 0) }
    expect(Math.abs(center(row) - center(track))).toBeLessThanOrEqual(1)
    // Each call's number is centered under its bar, the legend beside the axis taking none of its track.
    const offsets = await Promise.all(
        [1, 2, 3].map(async (n) => {
            const bar = await context.getByTestId(`context-call-${n}`).boundingBox()
            const name = await context.getByTestId(`context-axis-${n}`).boundingBox()
            return Math.abs(center(name) - center(bar))
        }),
    )
    expect(
        offsets.every((offset) => offset <= 1),
        `offsets: ${offsets.join(', ')}`,
    ).toBe(true)
})

test("a transcript's context chart folds to its line, which still shows the largest addition's row", async ({
    page,
}) => {
    await page.goto('runs/39')
    await settled(page)
    const transcript = page.getByTestId('transcript')
    const context = transcript.getByTestId('transcript-context')
    const calls = context.getByRole('radiogroup', { name: 'Model calls' })
    // Closed on arrival: the transcript's rows start under its header, its counts, and the chart's one line.
    await expect(context.getByRole('button', { name: 'Show chart' })).toHaveAttribute('aria-expanded', 'false')
    await expect(calls).toHaveCount(0)
    const top = await transcript.boundingBox()
    const first = await transcript.getByTestId('transcript-entries').locator('li').first().boundingBox()
    expect((first?.y ?? Infinity) - (top?.y ?? 0)).toBeLessThanOrEqual(100)

    // The largest addition shows its row with the chart closed: opened, scrolled to, focused.
    await context.getByTestId('context-largest').getByRole('button').click()
    const run = transcript.getByTestId('transcript-tool').filter({ hasText: 'npm test -- search' })
    await expect(run.locator('details')).toHaveAttribute('open', '')
    await expect(run.locator('summary')).toBeFocused()
    await expect(run.locator('summary')).toBeInViewport()
    await expect(calls).toHaveCount(0)

    // Opened, it stays open on a run's page across a reload, and a tick's page keeps its own choice.
    await context.getByRole('button', { name: 'Show chart' }).click()
    await expect(calls.getByRole('radio')).toHaveCount(3)
    await page.reload()
    await settled(page)
    await expect(calls.getByRole('radio')).toHaveCount(3)
    await expect(context.getByRole('button', { name: 'Hide chart' })).toHaveAttribute('aria-expanded', 'true')
    await page.goto('ticks/2')
    await settled(page)
    await expect(page.getByTestId('transcript-context')).toContainText('peak 9.3k at call 1')
})

test("a session of one model call has its context's line alone, and no By call", async ({ page }) => {
    await page.goto('ticks/2')
    await settled(page)
    const transcript = page.getByTestId('transcript')
    const context = transcript.getByTestId('transcript-context')
    await expect(context).toHaveText('contextpeak 9.3k at call 1')
    await expect(context.getByText('peak 9.3k at call 1')).toHaveAttribute(
        'title',
        /^9\d{3} tokens: ≈84 canopy’s prompt, ≈9\.2k the runtime’s own/u,
    )
    await expect(context.getByRole('button')).toHaveCount(0)
    await expect(transcript.getByRole('button', { name: 'By call' })).toHaveCount(0)

    // A runtime error printed under a second call the runtime counted no tokens for draws no bars either.
    await page.goto('runs/40')
    await settled(page)
    const run = page.getByTestId('transcript')
    await expect(run).toContainText('1 model call')
    await expect(run.getByTestId('transcript-context')).toHaveText('contextpeak 5.4k at call 1')
    await expect(run.getByTestId('transcript-context').getByRole('radio')).toHaveCount(0)
    await expect(run.getByRole('button', { name: 'By call' })).toHaveCount(0)
})

test("a tick's page shows its overseer's session under its decisions", async ({ page }) => {
    await page.goto('ticks/2')
    await settled(page)
    const transcript = page.getByTestId('transcript')
    const tools = transcript.getByTestId('transcript-tool')
    await expect(tools).toHaveCount(4)
    // Its session is named once, in the transcript's header, as a run's is.
    await expect(transcript).toContainText('session ses_tick2')
    await expect(page.locator('main').getByText('session ses_tick2')).toHaveCount(1)
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

test("a tool call's name takes its own width, so its command keeps the rest on either side of the rail's step", async ({
    page,
}) => {
    await page.goto('ticks/2')
    await settled(page)
    await windowWidth(page, 820)
    const transcript = page.getByTestId('transcript')
    const dispatch = transcript.getByTestId('transcript-tool').filter({ hasText: 'canopy dispatch ABC-104' })
    const command = dispatch.locator('summary').getByText('canopy dispatch ABC-104', { exact: false })
    const refusal = dispatch.locator('summary').getByText(/^dispatch refused/u)
    // In a narrow window the command keeps 300px, and its refusal reads to what refused it.
    await expect.poll(async () => (await command.boundingBox())?.width ?? 0).toBeGreaterThanOrEqual(300)
    expect(await cutAfter(refusal, 'run 43 is still working')).toBeLessThanOrEqual(0)
    // A short name takes no more than its own width.
    const bash = transcript
        .getByTestId('transcript-tool')
        .filter({ hasText: 'canopy decide ABC-101' })
        .locator('summary')
        .getByTitle('bash', { exact: true })
    expect(await spare(bash)).toBeLessThanOrEqual(1)

    // The whole rail takes its width from the pane, and the command gives up that much and no more.
    await windowWidth(page, FULL_RAIL - 1)
    const before = { panel: await widthOf(transcript), command: await widthOf(command) }
    await windowWidth(page, FULL_RAIL)
    const after = { panel: await widthOf(transcript), command: await widthOf(command) }
    expect(before.panel - after.panel).toBeGreaterThan(100)
    expect(Math.abs(before.command - after.command - (before.panel - after.panel))).toBeLessThanOrEqual(1)
})

test("a tick's output shows as written when asked, stderr included, and a tick that kept none says so once", async ({
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

    // With no file, there is no Output panel: the transcript, read from the same file, says why in its header, and
    // is that header alone.
    await page.goto('ticks/1')
    await settled(page)
    await expect(page.getByTestId('tick-output')).toHaveCount(0)
    const transcript = page.getByTestId('transcript')
    await expect(transcript.getByText('log gone')).toHaveAttribute(
        'title',
        'its log is gone, or is not a file canopy reads',
    )
    await expect(page.locator('main').getByText(/log gone|no output|its log is gone/u)).toHaveCount(1)
    // A header's height (`min-h-9`) and its borders, and no body under it.
    expect((await transcript.boundingBox())?.height).toBeLessThanOrEqual(40)
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

    // Its chore is its trail's step, linked there alone.
    await page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'chore:deps' }).click()
    await expect(page).toHaveURL(/\/chores\/deps$/u)

    await page.goto('chores/build-health/runs/4')
    await settled(page)
    await expect(page.getByTestId('transcript').getByText('no events yet')).toHaveAttribute(
        'title',
        'no events yet: they show here as the agent prints them',
    )
    await page.goto('chores/deps/runs/4')
    await expect(page.getByText("chore 'deps' has no run 4")).toBeVisible()
})

test('a run that does not exist, or a path that names none, says so', async ({ page }) => {
    await page.goto('runs/99')
    await expect(page.getByText('no run 99')).toBeVisible()
    await page.goto('runs/two')
    await expect(page.getByText("not a run: a run's id is a positive number")).toBeVisible()
})

/** An element's width on the page. */
async function widthOf(locator: Locator): Promise<number> {
    const box = await locator.boundingBox()
    return box?.width ?? 0
}

/** How far past the element's right edge the end of `text` in it falls, cut off: 0 or less when it shows whole. */
function cutAfter(locator: Locator, text: string): Promise<number> {
    return locator.evaluate((el, wanted) => {
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
        for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
            const at = node.textContent?.indexOf(wanted) ?? -1
            if (at >= 0) {
                const range = document.createRange()
                range.setStart(node, at)
                range.setEnd(node, at + wanted.length)
                return range.getBoundingClientRect().right - el.getBoundingClientRect().right
            }
        }
        return Number.POSITIVE_INFINITY
    }, text)
}

/** How much wider the element is than the text it holds. */
function spare(locator: Locator): Promise<number> {
    return locator.evaluate((el) => {
        const range = document.createRange()
        range.selectNodeContents(el)
        return el.getBoundingClientRect().width - range.getBoundingClientRect().width
    })
}
