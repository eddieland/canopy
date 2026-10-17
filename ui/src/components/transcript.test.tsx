import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Transcript, TranscriptEntry, TranscriptTokens } from '@/api/types'
import { setListOrder } from '@/lib/list-order'

import { TranscriptPanel } from './transcript'

afterEach(() => {
    cleanup()
    setListOrder('transcript', 'oldest')
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
    },
    { kind: 'text', call: 3, at: '2026-10-08T12:01:00Z', text: 'Trying again.', reasoning: false, cut: false },
]

function transcript(fields: Partial<Transcript> = {}): Transcript {
    return {
        session_id: 'ses_abc',
        status: 'read',
        entries: ENTRIES,
        prompt: { text: 'Implement ABC-1: sign in with SSO.', truncated: false },
        truncated: false,
        unreadable: 0,
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
        render(<TranscriptPanel transcript={undefined} running={false} />)
        expect(screen.getByTestId('panel-skeleton')).toBeDefined()
        expect(screen.queryByRole('searchbox')).toBeNull()
    })

    it.each([
        [
            'a live worker before its first event',
            'read',
            true,
            true,
            'no events yet: they show here as the worker prints them',
        ],
        [
            'a template that prints no events',
            'no_session',
            false,
            false,
            'the runtime reported no session: a template without --format json prints no events',
        ],
        ['a running session with no log yet', 'no_log', true, false, 'the session’s events reach the log when it ends'],
        [
            'an ended session whose log is gone',
            'no_log',
            false,
            false,
            'its log is gone, or is not a file canopy reads',
        ],
        [
            'a running session read before it ends',
            'read',
            true,
            false,
            'the session’s events reach the log when it ends',
        ],
        ['an ended session with no events', 'read', false, false, 'the log holds none of the session’s events'],
    ] as const)('says why it is empty for %s', (_, status, running, live, words) => {
        render(<TranscriptPanel transcript={transcript({ status, entries: [] })} running={running} live={live} />)
        expect(screen.getByText(words)).toBeDefined()
        expect(screen.queryByRole('searchbox')).toBeNull()
    })

    it('counts tool calls, failed and refused ones, model calls, and runtime errors, and says what is missing', () => {
        render(<TranscriptPanel transcript={transcript({ truncated: true, unreadable: 3 })} running={false} />)
        expect(says('3 tool calls, 1 failed, 1 refused')).toBe(true)
        expect(says('2 model calls')).toBe(true)
        expect(screen.getByText('1 runtime error')).toBeDefined()
        expect(screen.getByText('cut: the log holds more than a page shows')).toBeDefined()
        expect(screen.getByText('3 events could not be read')).toBeDefined()
    })

    it('says how each tool call ended on its row: its error, or the guard that refused a canopy command', () => {
        render(<TranscriptPanel transcript={transcript()} running={false} />)
        // A shell call's row says the command it ran, not the title the agent gave it.
        expect(call('npm test -- login').textContent).toContain('ENOENT: no such file or directory')
        expect(within(call('canopy decide')).getByText('refused: capacity')).toBeDefined()
    })

    it('says each model call’s tokens in and out as the CLI counts them, and a reason other than tool calls', () => {
        render(<TranscriptPanel transcript={transcript()} running={false} />)
        expect(call('1.2k in · 300 out').textContent).not.toContain('tool calls')
        const second = call('1.5k in · 60 out')
        expect(within(second).getByText('length')).toBeDefined()
        expect(within(second).getByTitle('1200 tokens').textContent).toBe('1.2k')
    })

    it('names the session in its header, but on a page that names it already', () => {
        const { rerender } = render(<TranscriptPanel transcript={transcript()} running={false} />)
        expect(screen.getByText('session ses_abc')).toBeDefined()
        rerender(<TranscriptPanel transcript={transcript()} running={false} session={false} />)
        expect(screen.queryByText('session ses_abc')).toBeNull()
    })

    it('keeps agent output as text, never markup', () => {
        const html = '<img src=x onerror="alert(1)"><b>bold</b>'
        render(
            <TranscriptPanel
                transcript={transcript({
                    entries: [{ kind: 'text', call: 1, at: AT, text: html, reasoning: false, cut: false }],
                })}
                running={false}
            />,
        )
        expect(screen.getByText(html)).toBeDefined()
        expect(screen.queryByRole('img')).toBeNull()
        expect(screen.queryByText('bold')).toBeNull()
    })

    it('keeps the rows with a line that holds the search, marks it, counts it, and opens the calls it is in', () => {
        render(<TranscriptPanel transcript={transcript()} running={false} />)
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
        render(<TranscriptPanel transcript={transcript()} running={false} />)
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
        render(<TranscriptPanel transcript={transcript()} running={false} />)
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
        render(<TranscriptPanel transcript={transcript()} running={false} />)
        expect(before('I will read the failing test first.', 'Trying again.')).toBe(true)
        fireEvent.click(screen.getByRole('button', { name: 'oldest first: show newest first' }))
        expect(before('Trying again.', 'I will read the failing test first.')).toBe(true)
        fireEvent.click(screen.getByRole('button', { name: 'newest first: show oldest first' }))
        expect(before('I will read the failing test first.', 'Trying again.')).toBe(true)
    })

    it('groups the events by model call, each opening to what it was sent and what it did', () => {
        render(<TranscriptPanel transcript={transcript()} running={false} />)
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
        render(<TranscriptPanel transcript={transcript({ prompt: null })} running={false} />)
        fireEvent.click(screen.getByRole('button', { name: 'By call' }))
        fireEvent.click(screen.getByRole('button', { name: 'All open' }))
        expect(screen.getAllByRole('region', { name: /^call \d input$/u })).toHaveLength(3)
        expect(screen.getByText('canopy kept no prompt for this session')).toBeDefined()
    })

    it('shows the row the context chart names in order and unsearched, open and scrolled to', () => {
        const scrolled = vi.spyOn(HTMLElement.prototype, 'scrollIntoView')
        render(<TranscriptPanel transcript={transcript()} running={false} />)
        search('rate')
        expect(rows().queryByText('I will read the failing test first.')).toBeNull()

        // The read's output is the most call 1 printed, so it is call 2's largest addition.
        const chart = screen.getByRole('region', { name: 'Context by model call' })
        const largest = within(chart).getAllByRole('button', { name: 'read filePath=src/login.ts' })[0]
        fireEvent.click(largest as HTMLElement)

        expect((find() as HTMLInputElement).value).toBe('')
        expect(rows().getByText('I will read the failing test first.')).toBeDefined()
        expect(call('filePath=src/login.ts').open).toBe(true)
        expect(scrolled).toHaveBeenCalledWith({ block: 'center' })
    })
})
