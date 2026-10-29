import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Transcript, TranscriptEntry, TranscriptTokens } from '@/api/types'
import type { TranscriptView } from '@/hooks/use-transcript-view'
import { setContextChartOpen } from '@/lib/context-chart-open'
import { setListOrder } from '@/lib/list-order'
import { TRANSCRIPT_BUDGET } from '@/lib/transcript'

import { TranscriptPanel } from './transcript'

afterEach(() => {
    cleanup()
    setListOrder('transcript', 'oldest')
    setContextChartOpen('run', false)
    setContextChartOpen('tick', false)
})

const AT = '2026-10-08T12:00:00Z'

function tokens(fields: Partial<TranscriptTokens>): TranscriptTokens {
    return { input: 0, cache_read: 0, cache_write: 0, output: 0, reasoning: 0, ...fields }
}

// A worker's session over three model calls: the first reads and runs, and fails one call; the second asks canopy for
// something the harness refuses, and the runtime errors; the third has started and not ended.
const ENTRIES: TranscriptEntry[] = [
    { kind: 'text', call: 1, at: AT, text: 'I will read the failing test first.', reasoning: false, cut: false },
    {
        kind: 'tool',
        call: 1,
        at: '2026-10-08T12:00:05Z',
        tool: 'bash',
        title: 'Runs the login tests',
        input: '{"command": "npm test -- login"}',
        output: 'ENOENT: no such file or directory',
        status: 'error',
        duration_ms: 840,
        cut: false,
    },
    {
        kind: 'tool',
        call: 1,
        at: '2026-10-08T12:00:09Z',
        tool: 'read',
        title: null,
        input: '{"filePath": "src/login.ts"}',
        output: 'export function login() {\n    return fetch("/api/session")\n}\n// '.padEnd(400, 'x'),
        status: 'completed',
        duration_ms: 12,
        cut: false,
    },
    {
        kind: 'step',
        call: 1,
        at: '2026-10-08T12:00:10Z',
        reason: 'tool-calls',
        split: tokens({ input: 1200, output: 300 }),
        tokens: 1500,
        cost_usd: 0.02,
        model: null,
    },
    {
        kind: 'tool',
        call: 2,
        at: '2026-10-08T12:00:42Z',
        tool: 'bash',
        title: null,
        input: '{"command": "canopy decide ABC-1 implement"}',
        output: 'Error: decide refused (capacity): every slot is taken',
        status: 'completed',
        duration_ms: 300,
        cut: false,
    },
    { kind: 'error', call: 2, at: '2026-10-08T12:00:50Z', name: 'ProviderError', message: 'rate limited' },
    {
        kind: 'step',
        call: 2,
        at: '2026-10-08T12:00:51Z',
        reason: 'length',
        split: tokens({ input: 300, cache_read: 1200, output: 50, reasoning: 10 }),
        tokens: 1560,
        cost_usd: 0.01,
        model: null,
    },
    { kind: 'text', call: 3, at: '2026-10-08T12:01:00Z', text: 'Trying again.', reasoning: false, cut: false },
]

const { page: PAGE, step: STEP } = TRANSCRIPT_BUDGET
// A transcript longer than a page and a fold's step: its last 50 rows are the fold's second click's.
const LONG = PAGE + STEP + 50

// A session that only talks: `said 1` to `said N`.
function said(n: number): TranscriptEntry[] {
    return Array.from({ length: n }, (_, i) => ({
        kind: 'text',
        call: 1,
        at: AT,
        text: `said ${i + 1}`,
        reasoning: false,
        cut: false,
    }))
}

// Model call `n`'s end, made by `model` when the API names it.
function step(n: number, model: string | null = null): TranscriptEntry {
    const split = tokens({ input: 100 })
    return { kind: 'step', call: n, at: AT, reason: 'tool-calls', split, tokens: 100, cost_usd: 0.01, model }
}

// A page's view of the transcript, held outside the panel; the test sets its row last shown.
const VIEW: TranscriptView = {
    grouped: false,
    setGrouped: () => {},
    typed: '',
    found: '',
    setTyped: () => {},
    target: null,
    show: () => {},
}

function transcript(fields: Partial<Transcript> = {}): Transcript {
    return {
        session_id: 'ses_abc',
        status: 'read',
        entries: ENTRIES,
        prompt: { text: 'Implement ABC-1: sign in with SSO.', truncated: false },
        truncated: false,
        unreadable: 0,
        removed_after_days: null,
        ...fields,
    }
}

// The transcript's search field.
function find(): HTMLElement {
    return screen.getByRole('searchbox', { name: 'Find lines in the transcript' })
}

function search(text: string) {
    fireEvent.change(find(), { target: { value: text } })
}

// The tool call or model call whose row or body holds `text`, as the disclosure it is.
function call(text: string): HTMLDetailsElement {
    const found = screen
        .getAllByRole('group')
        .filter((group): group is HTMLDetailsElement => group instanceof HTMLDetailsElement)
        .filter((group) => group.textContent.includes(text))
    expect(found).toHaveLength(1)
    return found[0] as HTMLDetailsElement
}

function allOpen(): HTMLElement {
    return screen.getByRole('button', { name: 'All open' })
}

// The transcript's rows in order, which the context chart's list of additions may also name.
function rows() {
    return within(screen.getByTestId('transcript-entries'))
}

// The transcript's context chart.
function chart() {
    return within(screen.getByRole('region', { name: 'Context by model call' }))
}

// Whether some element says `text` whole, however its pieces are split among elements.
function says(text: string): boolean {
    return screen.queryAllByText((_, element) => element?.textContent === text).length > 0
}

// Whether the row that says `a` is shown before the one that says `b`.
function before(a: string, b: string): boolean {
    const position = rows().getByText(a).compareDocumentPosition(rows().getByText(b))
    return (position & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
}

describe('TranscriptPanel', () => {
    it('shows a skeleton, with no search and no empty words, until the transcript arrives', () => {
        render(<TranscriptPanel transcript={undefined} running={false} page="run" />)
        expect(screen.getByTestId('panel-skeleton')).toBeDefined()
        expect(screen.queryByRole('searchbox')).toBeNull()
    })

    it.each([
        [
            'a running session before its first event',
            'read',
            true,
            'no events yet',
            'no events yet: they show here as the agent prints them',
        ],
        [
            'a running session with no log yet',
            'no_log',
            true,
            'no events yet',
            'no events yet: they show here as the agent prints them',
        ],
        [
            'a template that prints no events',
            'no_session',
            false,
            'no session',
            'the runtime reported no session: a template without --format json prints no events',
        ],
        [
            'an ended session whose log is gone',
            'no_log',
            false,
            'log gone',
            'its log is gone, or is not a file canopy reads',
        ],
        ['an ended session with no events', 'read', false, 'no events', 'the log holds none of the session’s events'],
    ] as const)('is its header alone for %s, saying why there', (_, status, running, words, reason) => {
        render(<TranscriptPanel transcript={transcript({ status, entries: [] })} running={running} page="run" />)
        expect(screen.getByText(words).title).toBe(reason)
        // The session it names, and nothing under the header: no rows, no search, no line saying it again.
        expect(screen.getByText('session ses_abc')).toBeDefined()
        expect(screen.queryByRole('searchbox')).toBeNull()
        expect(screen.queryByRole('list')).toBeNull()
        expect(screen.queryByText(reason)).toBeNull()
    })

    it('says after how many days retention removed an ended session’s log', () => {
        render(
            <TranscriptPanel
                transcript={transcript({ status: 'no_log', entries: [], removed_after_days: 30 })}
                running={false}
                page="run"
            />,
        )
        expect(screen.getByText('removed after 30 days').title).toBe(
            'removed after 30 days: your [retention] keeps a log that long once it ends',
        )
        expect(screen.queryByText('log gone')).toBeNull()
    })

    it('counts tool calls, failed and refused ones, model calls, and runtime errors, and says what is missing', () => {
        render(
            <TranscriptPanel transcript={transcript({ truncated: true, unreadable: 3 })} running={false} page="run" />,
        )
        expect(says('3 tool calls, 1 failed, 1 refused')).toBe(true)
        expect(says('2 model calls')).toBe(true)
        expect(screen.getByText('1 runtime error')).toBeDefined()
        expect(screen.getByText('cut: the log holds more than a page shows')).toBeDefined()
        expect(screen.getByText('3 events could not be read')).toBeDefined()
    })

    it('says how each tool call ended on its row: its error, or the guard that refused a canopy command', () => {
        render(<TranscriptPanel transcript={transcript()} running={false} page="run" />)
        // A shell call's row says the command it ran, not the title the agent gave it.
        expect(call('npm test -- login').textContent).toContain('ENOENT: no such file or directory')
        expect(within(call('canopy decide')).getByText('refused: capacity')).toBeDefined()
    })

    it('says a decide call’s decisions on its row, and opens to each with its rationale', () => {
        const decisions = [
            { key: 'ABC-1', action: 'wait', rationale: 'PR 8 waits on CI' },
            { key: 'ABC-2', action: 'done', rationale: 'merged by the operator' },
        ]
        const decide: TranscriptEntry = {
            kind: 'tool',
            call: 1,
            at: AT,
            tool: 'canopy_decide',
            title: null,
            input: JSON.stringify({ decisions }, null, 2),
            output: 'recorded wait for ABC-1\nrecorded done for ABC-2',
            status: 'completed',
            duration_ms: 20,
            cut: false,
        }
        render(<TranscriptPanel transcript={transcript({ entries: [decide] })} running={false} page="tick" />)
        const row = within(call('canopy_decide'))
        expect(row.getByText('ABC-1 wait, ABC-2 done')).toBeDefined()
        expect(row.getByText('2 decisions')).toBeDefined()
        const items = row.getAllByRole('listitem').map((item) => item.textContent)
        expect(items).toEqual(['ABC-1waitPR 8 waits on CI', 'ABC-2donemerged by the operator'])
    })

    it('says a ticket-set call’s settings on its row, and opens to each with what it sets', () => {
        const tickets = [
            { key: 'ABC-1', phase: 'approved', title: 'Fix login' },
            { key: 'ABC-2', repo: 'web', phase: 'merged', cursors: { review: '4', ci: '9' }, done: true },
        ]
        const set: TranscriptEntry = {
            kind: 'tool',
            call: 1,
            at: AT,
            tool: 'canopy_ticket-set',
            title: null,
            input: JSON.stringify({ tickets }, null, 2),
            output: 'updated ABC-1\nupdated ABC-2 (web)',
            status: 'completed',
            duration_ms: 20,
            cut: false,
        }
        render(<TranscriptPanel transcript={transcript({ entries: [set] })} running={false} page="tick" />)
        const row = within(call('canopy_ticket-set'))
        expect(row.getByText('ABC-1 approved title, ABC-2 (web) merged done cursors')).toBeDefined()
        expect(row.getByText('2 settings')).toBeDefined()
        const items = row.getAllByRole('listitem').map((item) => item.textContent)
        expect(items).toEqual(['ABC-1approvedFix login', 'ABC-2 (web)mergeddonereview 4ci 9'])
    })

    it('says each model call’s tokens in and out as the CLI counts them, and a reason other than tool calls', () => {
        render(<TranscriptPanel transcript={transcript()} running={false} page="run" />)
        expect(call('1.2k in · 300 out').textContent).not.toContain('tool calls')
        const second = call('1.5k in · 60 out')
        expect(within(second).getByText('length')).toBeDefined()
    })

    it('opens a model call in order to what it was sent and what it did, built only once opened', () => {
        render(<TranscriptPanel transcript={transcript()} running={false} page="run" />)
        const second = call('1.5k in · 60 out')
        expect(second.textContent).toContain('model call 2')
        expect(within(second).queryByRole('region', { name: 'call 2 input' })).toBeNull()

        second.open = true
        fireEvent(second, new Event('toggle'))
        const input = within(second).getByRole('region', { name: 'call 2 input' })
        expect(within(input).getByText('call 1’s input and output, then what its tools returned:')).toBeDefined()
        expect(within(input).getByText('ENOENT: no such file or directory')).toBeDefined()
        const output = within(second).getByRole('region', { name: 'call 2 output' })
        expect(within(output).getByText('rate limited')).toBeDefined()
        expect(within(second).getByTitle('1200 tokens').textContent).toBe('1.2k')

        // The first call was sent the prompt canopy kept.
        const first = call('1.2k in · 300 out')
        first.open = true
        fireEvent(first, new Event('toggle'))
        const sent = within(first).getByRole('region', { name: 'call 1 input' })
        expect(within(sent).getByText('Implement ABC-1: sign in with SSO.')).toBeDefined()
    })

    it('names the model of a split run’s first call, and of each call whose model is not the call before’s', () => {
        const opus = 'anthropic/claude-opus-4-1'
        const sonnet = 'anthropic/claude-sonnet-4-5'
        const entries: TranscriptEntry[] = [1, 2, 3].flatMap((n): TranscriptEntry[] => [
            { kind: 'text', call: n, at: AT, text: `said ${n}`, reasoning: false, cut: false },
            step(n, n === 3 ? sonnet : opus),
        ])
        render(<TranscriptPanel transcript={transcript({ entries })} running={false} page="run" />)
        expect(call('model call 1').textContent).toContain(opus)
        expect(call('model call 2').textContent).not.toContain('anthropic/')
        expect(call('model call 3').textContent).toContain(sonnet)
        expect(screen.getByTitle(`made by ${sonnet}`)).toBeDefined()

        // By call names them on the same calls.
        fireEvent.click(screen.getByRole('button', { name: 'By call' }))
        expect(screen.getByRole('button', { name: /call 1/u }).textContent).toContain(opus)
        expect(screen.getByRole('button', { name: /call 2/u }).textContent).not.toContain('anthropic/')
        expect(screen.getByRole('button', { name: /call 3/u }).textContent).toContain(sonnet)
    })

    it('names no model for a run one model served: its Run panel does', () => {
        render(<TranscriptPanel transcript={transcript()} running={false} page="run" />)
        expect(screen.queryByTitle(/^made by /u)).toBeNull()
    })

    it('names the session in its header', () => {
        render(<TranscriptPanel transcript={transcript()} running={false} page="run" />)
        expect(screen.getByText('session ses_abc')).toBeDefined()
    })

    it('keeps agent output as text, never markup', () => {
        const html = '<img src=x onerror="alert(1)"><b>bold</b>'
        render(
            <TranscriptPanel
                transcript={transcript({
                    entries: [{ kind: 'text', call: 1, at: AT, text: html, reasoning: false, cut: false }],
                })}
                running={false}
                page="run"
            />,
        )
        expect(screen.getByText(html)).toBeDefined()
        expect(screen.queryByRole('img')).toBeNull()
        expect(screen.queryByText('bold')).toBeNull()
    })

    it('keeps the rows with a line that holds the search, marks it, counts it, and opens the calls it is in', () => {
        render(<TranscriptPanel transcript={transcript()} running={false} page="run" />)
        search('LOGIN')

        // Two tool calls hold it: the shell call's command, in its row and its input; the read's path, in its row
        // and its input, and its output once.
        expect(screen.getByTestId('transcript-found').textContent).toBe('5 lines, 2 rows')
        expect(rows().queryByText('I will read the failing test first.')).toBeNull()
        expect(rows().queryByText('rate limited')).toBeNull()
        expect(call('npm test -- login').open).toBe(true)
        expect(call('filePath=src/login.ts').open).toBe(true)
        expect(screen.getAllByRole('mark').map((mark) => mark.textContent)).toContain('login')
        expect(allOpen().getAttribute('aria-pressed')).toBe('true')
    })

    it('says when no line holds the search, and shows every row again once it is cleared or escaped', () => {
        render(<TranscriptPanel transcript={transcript()} running={false} page="run" />)
        search('zebra')
        expect(screen.getByText('no line holds “zebra”')).toBeDefined()
        expect(screen.getByTestId('transcript-found').textContent).toBe('0 lines, 0 rows')

        fireEvent.click(screen.getByRole('button', { name: "Clear the transcript's search" }))
        expect(rows().getByText('I will read the failing test first.')).toBeDefined()
        expect(screen.queryByTestId('transcript-found')).toBeNull()

        search('rate')
        expect(rows().queryByText('I will read the failing test first.')).toBeNull()
        fireEvent.keyDown(find(), { key: 'Escape' })
        expect((find() as HTMLInputElement).value).toBe('')
        expect(rows().getByText('I will read the failing test first.')).toBeDefined()
    })

    it('opens and closes every call with All open, over what a search opened, until a new search', () => {
        render(<TranscriptPanel transcript={transcript()} running={false} page="run" />)
        expect(call('npm test -- login').open).toBe(false)
        fireEvent.click(allOpen())
        expect(call('npm test -- login').open).toBe(true)
        expect(call('canopy decide').open).toBe(true)
        fireEvent.click(allOpen())
        expect(call('canopy decide').open).toBe(false)

        search('login')
        expect(call('filePath=src/login.ts').open).toBe(true)
        // Turned off under the search, it closes what the search opened.
        fireEvent.click(allOpen())
        expect(allOpen().getAttribute('aria-pressed')).toBe('false')
        expect(call('filePath=src/login.ts').open).toBe(false)
        // A new search opens what it finds again.
        search('login.ts')
        expect(call('filePath=src/login.ts').open).toBe(true)
    })

    it('flips to newest first and back', () => {
        render(<TranscriptPanel transcript={transcript()} running={false} page="run" />)
        expect(before('I will read the failing test first.', 'Trying again.')).toBe(true)
        fireEvent.click(screen.getByRole('button', { name: 'oldest first: show newest first' }))
        expect(before('Trying again.', 'I will read the failing test first.')).toBe(true)
        fireEvent.click(screen.getByRole('button', { name: 'newest first: show oldest first' }))
        expect(before('I will read the failing test first.', 'Trying again.')).toBe(true)
    })

    it('groups the events by model call, each opening to what it was sent and what it did', () => {
        render(<TranscriptPanel transcript={transcript()} running={false} page="run" />)
        fireEvent.click(screen.getByRole('button', { name: 'By call' }))

        // By call keeps the whole transcript: there is no search.
        expect(screen.queryByRole('searchbox')).toBeNull()
        const first = screen.getByRole('button', { name: /call 1/u })
        expect(first.textContent).toContain('I will read the failing test first. · bash, read')
        expect(screen.getByRole('button', { name: /call 3/u }).textContent).toContain('unfinished')

        // A call's body is built only once it is opened.
        expect(screen.queryByRole('region', { name: 'call 1 input' })).toBeNull()
        fireEvent.click(first)
        const input = screen.getByRole('region', { name: 'call 1 input' })
        expect(within(input).getByText('Implement ABC-1: sign in with SSO.')).toBeDefined()
        expect(within(input).getByText(/sent after the agent’s definition/u)).toBeDefined()

        // A later call was sent what the call before's tools returned.
        fireEvent.click(screen.getByRole('button', { name: /call 2/u }))
        const second = screen.getByRole('region', { name: 'call 2 input' })
        expect(within(second).getByText('call 1’s input and output, then what its tools returned:')).toBeDefined()
        expect(within(second).getByText('ENOENT: no such file or directory')).toBeDefined()
        const output = screen.getByRole('region', { name: 'call 2 output' })
        expect(within(output).getByText('rate limited')).toBeDefined()

        fireEvent.click(screen.getByRole('button', { name: 'By call' }))
        expect(find()).toBeDefined()
    })

    it('says when canopy kept no prompt for the first call', () => {
        render(<TranscriptPanel transcript={transcript({ prompt: null })} running={false} page="run" />)
        fireEvent.click(screen.getByRole('button', { name: 'By call' }))
        fireEvent.click(screen.getByRole('button', { name: 'All open' }))
        expect(screen.getAllByRole('region', { name: /^call \d input$/u })).toHaveLength(3)
        expect(screen.getByText('canopy kept no prompt for this session')).toBeDefined()
    })

    it('offers By call only with two model calls or more', () => {
        const one = ENTRIES.filter((e) => e.call === 1)
        render(<TranscriptPanel transcript={transcript({ entries: one })} running={false} page="run" />)
        expect(screen.getByText('1 model call')).toBeDefined()
        expect(screen.queryByRole('button', { name: 'By call' })).toBeNull()
    })

    it('keeps the context chart closed to its line, opened or not by each kind of page', () => {
        const { rerender } = render(<TranscriptPanel transcript={transcript()} running={false} page="run" />)
        expect(chart().queryByRole('radiogroup', { name: 'Model calls' })).toBeNull()

        fireEvent.click(chart().getByRole('button', { name: 'Show chart' }))
        expect(chart().getByRole('radiogroup', { name: 'Model calls' })).toBeDefined()
        expect(chart().getByRole('button', { name: 'Hide chart' }).getAttribute('aria-expanded')).toBe('true')

        // A tick's page keeps its own choice; a run's keeps the one made on it.
        rerender(<TranscriptPanel transcript={transcript()} running={false} page="tick" />)
        expect(chart().queryByRole('radiogroup')).toBeNull()
        rerender(<TranscriptPanel transcript={transcript()} running={false} page="run" />)
        expect(chart().getByRole('radiogroup')).toBeDefined()
    })

    it('folds long thinking to its first lines, and shows the rest on a click', () => {
        const thought = Array.from({ length: 8 }, (_, i) => `thought ${i + 1}`).join('\n')
        const entries: TranscriptEntry[] = [
            { kind: 'text', call: 1, at: AT, text: thought, reasoning: true, cut: false },
        ]
        render(<TranscriptPanel transcript={transcript({ entries })} running={false} page="run" />)
        expect(rows().getByText(/thought 4/u)).toBeDefined()
        expect(rows().queryByText(/thought 5/u)).toBeNull()

        fireEvent.click(rows().getByRole('button', { name: 'show 4 more lines', expanded: false }))
        expect(rows().getByText(/thought 8/u)).toBeDefined()
        fireEvent.click(rows().getByRole('button', { name: 'show less', expanded: true }))
        expect(rows().queryByText(/thought 8/u)).toBeNull()
    })

    it('drops the blank lines thinking ends on, whole or folded', () => {
        const entries: TranscriptEntry[] = [
            { kind: 'text', call: 1, at: AT, text: 'a plan\n\n', reasoning: true, cut: false },
            { kind: 'text', call: 1, at: AT, text: 'one\ntwo\nthree\n\nfour\nfive', reasoning: true, cut: false },
        ]
        render(<TranscriptPanel transcript={transcript({ entries })} running={false} page="run" />)
        expect(
            rows()
                .getByText(/a plan/u)
                .closest('p')?.textContent,
        ).toBe('thinkinga plan')
        expect(rows().getByText(/one/u).closest('p')?.textContent).toBe('thinkingone\ntwo\nthree')
    })

    it('shows long thinking whole with All open, or when the search holds a line it folds away', () => {
        const thought = Array.from({ length: 8 }, (_, i) => `thought ${i + 1}`).join('\n')
        const entries: TranscriptEntry[] = [
            { kind: 'text', call: 1, at: AT, text: thought, reasoning: true, cut: false },
            ...ENTRIES,
        ]
        render(<TranscriptPanel transcript={transcript({ entries })} running={false} page="run" />)
        fireEvent.click(allOpen())
        expect(rows().getByText(/thought 8/u)).toBeDefined()
        fireEvent.click(allOpen())
        expect(rows().queryByText(/thought 8/u)).toBeNull()

        search('thought 2')
        expect(rows().queryByText(/thought 8/u)).toBeNull()
        search('thought 7')
        expect(rows().getByRole('mark').textContent).toBe('thought 7')
        expect(rows().getByRole('button', { name: 'show less' })).toBeDefined()
    })

    it('draws a page of a long transcript’s rows, and a fold after them that shows more', () => {
        render(<TranscriptPanel transcript={transcript({ entries: said(LONG) })} running={false} page="run" />)
        expect(rows().getByText(`said ${PAGE}`)).toBeDefined()
        expect(rows().queryByText(`said ${PAGE + 1}`)).toBeNull()

        fireEvent.click(screen.getByRole('button', { name: `Show ${STEP} of ${STEP + 50} more rows` }))
        expect(rows().getByText(`said ${PAGE + STEP}`)).toBeDefined()
        expect(rows().queryByText(`said ${PAGE + STEP + 1}`)).toBeNull()
        fireEvent.click(screen.getByRole('button', { name: 'Show 50 more rows' }))
        expect(rows().getByText(`said ${LONG}`)).toBeDefined()
        expect(screen.queryByRole('button', { name: /more rows/u })).toBeNull()
    })

    it('searches every entry, drawn or not, and draws what it keeps within the same budget', () => {
        render(<TranscriptPanel transcript={transcript({ entries: said(LONG) })} running={false} page="run" />)
        search(`said ${LONG - 1}`)
        expect(rows().getByText(`said ${LONG - 1}`)).toBeDefined()

        search('said')
        expect(screen.getByTestId('transcript-found').textContent).toBe(`${LONG} lines, ${LONG} rows`)
        fireEvent.click(screen.getByRole('button', { name: `Show ${STEP} of ${STEP + 50} more rows` }))
        expect(screen.getByRole('button', { name: 'Show 50 more rows' })).toBeDefined()
        // A new search draws a page of what it keeps again.
        search('said 1')
        search('said')
        expect(screen.getByRole('button', { name: `Show ${STEP} of ${STEP + 50} more rows` })).toBeDefined()
    })

    it('opens only the rows it draws with All open', () => {
        const entries = Array.from({ length: LONG }, (_, i) => ({ ...(ENTRIES[2] as TranscriptEntry), call: i + 1 }))
        render(<TranscriptPanel transcript={transcript({ entries })} running={false} page="run" />)
        fireEvent.click(allOpen())
        const open = screen.getAllByRole('group').filter((group) => group instanceof HTMLDetailsElement && group.open)
        expect(open).toHaveLength(PAGE)
    })

    // Draws a page of calls twice over: a second in happy-dom, past the default's five on a busy runner.
    it('draws a page of a long session’s calls by call, and a fold after them', { timeout: 30_000 }, () => {
        const entries = said(PAGE + 50).flatMap((entry, i) => [{ ...entry, call: i + 1 }, step(i + 1)])
        render(<TranscriptPanel transcript={transcript({ entries })} running={false} page="run" />)
        fireEvent.click(screen.getByRole('button', { name: 'By call' }))
        expect(screen.getByRole('button', { name: new RegExp(`^\\S+ call ${PAGE} `, 'u') })).toBeDefined()
        expect(screen.queryByRole('button', { name: new RegExp(`^\\S+ call ${PAGE + 1} `, 'u') })).toBeNull()
        fireEvent.click(screen.getByRole('button', { name: 'Show 50 more calls' }))
        expect(screen.getByRole('button', { name: new RegExp(`^\\S+ call ${PAGE + 50} `, 'u') })).toBeDefined()
    })

    it('draws on through the row a page shows from outside it, before scrolling to it', () => {
        const scrolled = vi.spyOn(HTMLElement.prototype, 'scrollIntoView')
        const view = { ...VIEW, target: { i: LONG - 20, round: 1 } }
        render(
            <TranscriptPanel transcript={transcript({ entries: said(LONG) })} running={false} page="run" view={view} />,
        )
        expect(rows().getByText(`said ${LONG - 19}`)).toBeDefined()
        expect(rows().queryByText(`said ${LONG - 18}`)).toBeNull()
        expect(scrolled).toHaveBeenCalledWith({ block: 'center' })
    })

    it('draws through a shown row only for its showing, so a later search keeps to the page', () => {
        const entries = said(LONG)
        const view = { ...VIEW, target: { i: LONG - 20, round: 1 } }
        const { rerender } = render(
            <TranscriptPanel transcript={transcript({ entries })} running={false} page="run" view={view} />,
        )
        expect(rows().getByText(`said ${LONG - 19}`)).toBeDefined()
        rerender(
            <TranscriptPanel
                transcript={transcript({ entries })}
                running={false}
                page="run"
                view={{ ...view, found: 'said' }}
            />,
        )
        expect(rows().queryByText(`said ${PAGE + 1}`)).toBeNull()
        expect(screen.getByRole('button', { name: `Show ${STEP} of ${STEP + 50} more rows` })).toBeDefined()
        // Cleared, the search starts again at a page too, not at the row shown before it.
        rerender(<TranscriptPanel transcript={transcript({ entries })} running={false} page="run" view={view} />)
        expect(rows().queryByText(`said ${PAGE + 1}`)).toBeNull()
    })

    it('shows the row the context chart names in order and unsearched, open and scrolled to', () => {
        const scrolled = vi.spyOn(HTMLElement.prototype, 'scrollIntoView')
        render(<TranscriptPanel transcript={transcript()} running={false} page="run" />)
        search('rate')
        expect(rows().queryByText('I will read the failing test first.')).toBeNull()

        // The read's output is the most call 1 printed, so it is call 2's largest addition, on the chart's line even
        // while the chart is closed.
        expect(chart().queryByRole('radiogroup')).toBeNull()
        fireEvent.click(chart().getByRole('button', { name: 'read filePath=src/login.ts' }))

        expect((find() as HTMLInputElement).value).toBe('')
        expect(rows().getByText('I will read the failing test first.')).toBeDefined()
        expect(call('filePath=src/login.ts').open).toBe(true)
        expect(scrolled).toHaveBeenCalledWith({ block: 'center' })
    })
})
