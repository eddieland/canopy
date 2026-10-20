import { describe, expect, it } from 'vitest'

import type { TranscriptEntry, TranscriptStep, TranscriptTool } from '@/api/types'

import {
    byCall,
    contextShape,
    callLine,
    drawnRows,
    duration,
    elapsed,
    endedOn,
    findQueryOf,
    foldText,
    hitsIn,
    moreLabel,
    outcome,
    pretty,
    runTokens,
    sentTokens,
    shownOutput,
    signed,
    startOf,
    summary,
    tally,
    tokenCount,
    tokensCell,
    TRANSCRIPT_BUDGET,
    wroteTokens,
} from './transcript'

describe('elapsed', () => {
    it('counts from the start, with hours only when there are some', () => {
        const start = '2026-10-08T10:30:00Z'
        expect(elapsed('2026-10-08T10:30:42Z', start)).toBe('+0:42')
        expect(elapsed('2026-10-08T10:42:05Z', start)).toBe('+12:05')
        expect(elapsed('2026-10-08T11:32:09Z', start)).toBe('+1:02:09')
    })

    it('is empty without a time, and never negative', () => {
        expect(elapsed(null, '2026-10-08T10:30:00Z')).toBe('')
        expect(elapsed('2026-10-08T10:30:00Z', null)).toBe('')
        expect(elapsed('2026-10-08T10:29:00Z', '2026-10-08T10:30:00Z')).toBe('+0:00')
    })
})

describe('duration and tokenCount', () => {
    it('read as the CLI says them', () => {
        expect([duration(840), duration(14_000), duration(185_000)]).toEqual(['840ms', '14s', '3m 05s'])
        expect([signed(4310), signed(-2000), signed(0)]).toEqual(['+4.3k', '-2.0k', '+0'])
        expect([tokenCount(950), tokenCount(12_340), tokenCount(1_240_000)]).toEqual(['950', '12.3k', '1.2M'])
    })
})

describe('runTokens', () => {
    it('reads as the CLI says it, the peak only when it was recorded', () => {
        expect(runTokens(3460, 9000)).toBe(', 3.5k tokens, 9.0k peak context')
        expect(runTokens(3460, null)).toBe(', 3.5k tokens')
        expect(runTokens(null, null)).toBe('')
    })
})

describe('tokensCell', () => {
    it('names what it counts, and is a dash when nothing reported one', () => {
        expect([tokensCell(3460, 'tokens'), tokensCell(9000, 'peak')]).toEqual(['3.5k tokens', '9.0k peak'])
        expect(tokensCell(null, 'peak')).toBe('–')
    })
})

const tool = (status: 'completed' | 'error', fields: Partial<TranscriptTool> = {}): TranscriptTool => ({
    kind: 'tool',
    at: '2026-10-08T10:31:00Z',
    tool: 'bash',
    status,
    title: null,
    input: '{}',
    output: '',
    duration_ms: null,
    cut: false,
    call: 1,
    ...fields,
})

const shell = (command: string, output: string): TranscriptTool =>
    tool('completed', { input: JSON.stringify({ command, description: 'what the agent said' }), output })

describe('tally and startOf', () => {
    const entries: TranscriptEntry[] = [
        { kind: 'text', at: null, text: 'hi', reasoning: false, cut: false, call: 1 },
        tool('completed'),
        tool('error'),
        shell('canopy dispatch ABC-1', 'Error: dispatch refused (capacity): 2 of 2 running'),
        { kind: 'step', at: '2026-10-08T10:32:00Z', reason: 'stop', cost_usd: 0.1, tokens: 10, split: null, call: 1 },
        { kind: 'error', at: null, name: 'APIError', message: '', call: 1 },
    ]

    it('counts tool calls, failed and refused ones, model calls, and errors', () => {
        expect(tally(entries)).toEqual({ tools: 3, failed: 1, refused: 1, calls: 1, errors: 1 })
    })

    it('starts at the first entry with a time', () => {
        expect(startOf(entries)).toBe('2026-10-08T10:31:00Z')
        expect(startOf([])).toBeNull()
    })
})

const runtimeError = (message: string): TranscriptEntry => ({
    kind: 'error',
    at: '2026-10-08T10:33:00Z',
    name: 'APIError',
    message,
    call: 2,
})

describe('endedOn', () => {
    const refused = shell('canopy decide ABC-1 implement', 'Error: decide refused (capacity): every slot is taken')

    it("is the last runtime error, its message's first line, over any failed call after it", () => {
        const entries = [
            runtimeError('first'),
            tool('error', { output: 'ENOENT' }),
            runtimeError('Rate limited: retry after 60s\n    at fetch (provider.ts:12)'),
        ]
        expect(endedOn(entries)).toEqual({ i: 2, entry: entries[2], line: 'Rate limited: retry after 60s' })
        expect(endedOn([runtimeError('stopped'), tool('error', { output: 'ENOENT' })])?.i).toBe(0)
    })

    it('is else the last failed or refused tool call, with how it ended, else what it did', () => {
        const failed = tool('error', { output: 'ENOENT: no such file\nat open' })
        expect(endedOn([failed, tool('completed')])).toEqual({ i: 0, entry: failed, line: 'ENOENT: no such file' })
        expect(endedOn([failed, refused])?.line).toBe('decide refused (capacity): every slot is taken')
        expect(endedOn([tool('error', { title: 'Runs the tests' })])?.line).toBe('Runs the tests')
    })

    it('is null for a session that holds neither', () => {
        expect(endedOn([tool('completed'), shell('ls', 'a\nb')])).toBeNull()
        expect(endedOn([])).toBeNull()
    })
})

describe('summary', () => {
    it("is a shell call's command, on one line, whatever its title says", () => {
        const call = shell('canopy decide ABC-1 wait\n  --rationale "PR 8 waits"', '')
        expect(summary({ ...call, title: 'Record wait on ABC-1' })).toBe(
            'canopy decide ABC-1 wait --rationale "PR 8 waits"',
        )
    })

    it("is the runtime's title for any other call that has one", () => {
        expect(summary(tool('completed', { title: 'src/a.ts', input: '{"filePath": "/repo/src/a.ts"}' }))).toBe(
            'src/a.ts',
        )
    })

    it("is an untitled call's short values, as key=value, quoted when they hold a space", () => {
        const input = JSON.stringify({
            method: 'get_status',
            owner: 'acme',
            pullNumber: 88,
            draft: false,
            jql: 'project = ABC',
            fields: ['summary'],
            body: 'x'.repeat(81),
        })
        expect(summary(tool('completed', { input }))).toBe(
            'method=get_status owner=acme pullNumber=88 draft=false jql="project = ABC"',
        )
    })

    it('is empty for an input with nothing short, or one cut short', () => {
        expect(summary(tool('completed', { input: '{"fields": []}' }))).toBe('')
        expect(summary(tool('completed', { input: '{"command": "np' }))).toBe('')
        expect(summary(tool('completed', { input: '[]' }))).toBe('')
    })
})

describe('outcome', () => {
    it('names the guard of a canopy command the harness refused, though the runtime says it completed', () => {
        const refused = shell('canopy dispatch ABC-1 --kind implement', 'Error: dispatch refused (capacity): 2 of 2')
        expect(outcome(refused)).toEqual({
            verdict: 'refused',
            guard: 'capacity',
            line: 'dispatch refused (capacity): 2 of 2',
        })
    })

    it('fails a canopy command that printed any other error, and a call the runtime says failed', () => {
        expect(outcome(shell('canopy decide ABC-1 wait', 'Error: no ticket ABC-1'))).toEqual({
            verdict: 'failed',
            guard: null,
            line: 'no ticket ABC-1',
        })
        expect(outcome(tool('error', { output: '\nFile not found: /a.ts\nat read' }))).toEqual({
            verdict: 'failed',
            guard: null,
            line: 'File not found: /a.ts',
        })
    })

    it("reads only canopy's own errors: another command's output is what it printed", () => {
        expect(outcome(shell('grep Error: log', 'Error: x')).verdict).toBe('done')
    })

    it('shows an output of one short line, and no line for a longer one or for JSON', () => {
        expect(outcome(shell('canopy decide ABC-1 wait', 'recorded decision 8\n')).line).toBe('recorded decision 8')
        expect(outcome(shell('git push', 'To github.com:a/b.git\n * [new branch]')).line).toBeNull()
        expect(outcome(tool('completed', { output: 'x'.repeat(201) })).line).toBeNull()
        expect(outcome(tool('completed', { output: '{"number": 88}' })).line).toBeNull()
        expect(outcome(tool('completed')).line).toBeNull()
    })
})

describe('pretty', () => {
    it('indents JSON, and leaves anything else, a cut JSON included, as printed', () => {
        expect(pretty('{"a": [1]}')).toBe('{\n  "a": [\n    1\n  ]\n}')
        expect(pretty('{"a": [1')).toBe('{"a": [1')
        expect(pretty('42')).toBe('42')
        expect(pretty('PASS  2 tests')).toBe('PASS  2 tests')
    })

    it('keeps every value as written: a number past a double, an escape, an output already indented', () => {
        expect(pretty('{"id":12345678901234567890,"n":1.10}')).toBe('{\n  "id": 12345678901234567890,\n  "n": 1.10\n}')
        expect(pretty('["caf\\u00e9"]')).toBe('[\n  "caf\\u00e9"\n]')
        expect(pretty('{\n    "a": {}\n}')).toBe('{\n  "a": {}\n}')
    })
})

describe('findQueryOf', () => {
    it('trims the ends, keeping what is between them as typed', () => {
        expect(findQueryOf('  gh pr  view ')).toBe('gh pr  view')
        expect(findQueryOf(' \t ')).toBeNull()
        expect(findQueryOf('')).toBeNull()
    })
})

describe('hitsIn', () => {
    it('counts the lines of a row that hold the query, in either case, each line once', () => {
        const said = text('Reading the box.\nthe BOX and the box\nnothing here', null)
        expect(hitsIn(said, 'box')).toEqual({ row: 2, body: 0 })
        expect(hitsIn(said, 'box.\nthe')).toEqual({ row: 0, body: 0 })
    })

    it("reads a tool call's row as shown, and its input and output as it opens to them", () => {
        const call = shell('gh pr view 88', '{"number": 88,\n"title": "Debounce search"}')
        // The row's command, and the output's pretty lines.
        expect(hitsIn(call, 'gh pr')).toEqual({ row: 1, body: 1 })
        expect(hitsIn(call, 'debounce')).toEqual({ row: 0, body: 1 })
        expect(hitsIn(call, '"number": 88')).toEqual({ row: 0, body: 1 })
        expect(hitsIn(tool('completed', { tool: 'github_get_pr' }), 'GET_PR')).toEqual({ row: 1, body: 0 })
        expect(hitsIn(tool('completed'), 'no output')).toEqual({ row: 0, body: 1 })
    })

    it('takes regex characters literally, and finds nothing in a model call', () => {
        const error: TranscriptEntry = {
            kind: 'error',
            at: null,
            name: 'APIError',
            message: 'retry (after 60s)',
            call: null,
        }
        expect(hitsIn(error, '(after')).toEqual({ row: 1, body: 0 })
        expect(hitsIn(error, 'a.i')).toEqual({ row: 0, body: 0 })
        expect(hitsIn(step(1, 'stop'), 'stop')).toEqual({ row: 0, body: 0 })
    })
})

describe('foldText', () => {
    it('shows text up to one line over its lines whole', () => {
        expect(foldText('a\nb\nc\nd\ne', 4)).toEqual({ shown: 'a\nb\nc\nd\ne', hidden: 0 })
        expect(foldText('one line', 4)).toEqual({ shown: 'one line', hidden: 0 })
    })

    it('keeps the first lines of longer text, and counts the rest', () => {
        expect(foldText('a\nb\nc\nd\ne\nf', 4)).toEqual({ shown: 'a\nb\nc\nd', hidden: 2 })
    })

    it('counts a long line as the lines it wraps to, and cuts it where a word ends', () => {
        const long = 'word '.repeat(200).trim()
        const { shown, hidden } = foldText(long, 4)
        expect(hidden).toBe(6)
        expect(shown.endsWith('word…')).toBe(true)
        expect(shown.length).toBeLessThanOrEqual(400)
    })
})

describe('shownOutput', () => {
    it('is the output laid out, or says there is none', () => {
        expect(shownOutput(tool('completed', { output: '{"a":1}' }))).toBe(pretty('{"a":1}'))
        expect(shownOutput(tool('completed'))).toBe('no output')
    })
})

const text = (value: string, call: number | null, reasoning = false): TranscriptEntry => ({
    kind: 'text',
    at: null,
    text: value,
    reasoning,
    cut: false,
    call,
})

const step = (call: number, reason = 'tool-calls'): TranscriptStep => ({
    kind: 'step',
    at: null,
    reason,
    cost_usd: 0.1,
    tokens: 10,
    split: null,
    call,
})

describe('byCall', () => {
    it('gives each call after the first what its tools returned to the call before, and keeps its end apart', () => {
        const read = tool('completed', { tool: 'read', output: 'file', call: 1 })
        const failed = tool('error', { tool: 'read', output: 'not found', call: 1 })
        const early: TranscriptEntry = { kind: 'error', at: null, name: 'early', message: '', call: null }
        const { before, calls } = byCall([
            early,
            text('reading', 1),
            read,
            failed,
            step(1),
            text('done', 2),
            step(2, 'stop'),
        ])
        expect(before).toEqual([early])
        expect(calls).toEqual([
            { n: 1, returned: [], output: [text('reading', 1), read, failed], end: step(1) },
            { n: 2, returned: [read, failed], output: [text('done', 2)], end: step(2, 'stop') },
        ])
    })

    it('leaves a call the session ended in without an end', () => {
        const { calls } = byCall([text('one', 1), step(1), text('two', 2)])
        expect(calls.map((c) => [c.n, c.end])).toEqual([
            [1, step(1)],
            [2, null],
        ])
        expect(byCall([text('no calls marked', null)]).calls).toEqual([])
    })
})

describe('callLine', () => {
    it("is a call's first text, then its tools by name, counted, then its errors", () => {
        const [call] = byCall([
            text('thinking it over', 1, true),
            text('I will read\nboth files.', 1),
            tool('completed', { tool: 'read' }),
            tool('completed', { tool: 'read' }),
            tool('completed', { tool: 'bash' }),
            { kind: 'error', at: null, name: 'APIError', message: '', call: 1 },
        ]).calls
        expect(call && callLine(call)).toBe('I will read both files. · read ×2, bash · 1 runtime error')
    })
})

describe('sentTokens and wroteTokens', () => {
    it('count what a call was sent, cached or not, and what it wrote, reasoning included', () => {
        const split = { input: 10, cache_read: 300, cache_write: 20, output: 5, reasoning: 2 }
        expect([sentTokens(split), wroteTokens(split)]).toEqual([330, 7])
    })
})

// A call's end, sent `n` tokens: a quarter fresh, the rest read from the cache.
const sent = (call: number, n: number): TranscriptStep => ({
    ...step(call),
    split: { input: n / 4, cache_read: n - n / 4, cache_write: 0, output: 100, reasoning: 0 },
})

describe('contextShape', () => {
    const prompt = { text: 'x'.repeat(4000), truncated: false }

    it("splits the first call into canopy's prompt and the runtime's own, and shares a step up by characters", () => {
        const big = tool('completed', { input: '{}', output: 'y'.repeat(2998), call: 1 })
        const small = tool('completed', { input: '{}', output: 'y'.repeat(998), call: 1 })
        const entries = [text('ab', 1), small, big, sent(1, 12_000), text('done', 2), sent(2, 15_000)]
        const shape = contextShape(entries, prompt)
        expect(shape.prompt).toBe(1000)
        expect(shape.calls.map((c) => [c.n, c.sent, c.carried, c.added, c.step])).toEqual([
            [1, 12_000, 11_000, 1000, null],
            [2, 15_000, 12_000, 3000, 3000],
        ])
        // Largest first, each the share of the step its characters hold, linked by its place in the transcript.
        expect(shape.calls[1]?.additions.map((a) => [a.i, a.chars, a.tokens])).toEqual([
            [2, 3000, 2249],
            [1, 1000, 750],
            [0, 2, 1],
        ])
        expect(shape.peak?.n).toBe(2)
        expect(shape.largest?.call.n).toBe(2)
        expect(shape.largest?.addition.entry).toBe(big)
    })

    it('finds the largest addition across steps, not in the largest step', () => {
        const one = tool('completed', { output: 'a'.repeat(1000), call: 1 })
        const two = tool('completed', { output: 'b'.repeat(1000), call: 1 })
        const three = tool('completed', { output: 'c'.repeat(1000), call: 2 })
        const shape = contextShape([one, two, sent(1, 1000), three, sent(2, 5000), sent(3, 8000)], null)
        expect(shape.calls.map((c) => c.step)).toEqual([null, 4000, 3000])
        expect(shape.largest?.addition.entry).toBe(three)
        expect(shape.largest?.addition.tokens).toBe(3000)
    })

    it('adds nothing where the context shrank, and leaves a call the runtime counted none of empty', () => {
        const read = tool('completed', { output: 'file', call: 1 })
        const shape = contextShape([read, sent(1, 9000), sent(2, 7000), step(3), sent(4, 8000)], null)
        expect(shape.calls.map((c) => [c.sent, c.carried, c.added, c.step, c.additions.length])).toEqual([
            [9000, 9000, 0, null, 0],
            [7000, 7000, 0, -2000, 0],
            [null, 0, 0, null, 0],
            [8000, 8000, 0, null, 0],
        ])
        expect(shape.peak?.n).toBe(1)
        expect(shape.largest).toBeNull()
    })

    it('never sets the prompt above what the first call was sent, and has no peak without counts', () => {
        expect(contextShape([sent(1, 400)], prompt).calls[0]).toMatchObject({ carried: 0, added: 400 })
        expect(contextShape([text('hi', 1), step(1)], prompt).peak).toBeNull()
        expect(contextShape([text('before any call', null)], null).calls).toEqual([])
    })
})

describe('drawnRows', () => {
    const { page, step: more } = TRANSCRIPT_BUDGET

    it('draws every row of a transcript within a page, and a page of a longer one', () => {
        expect(drawnRows(12, 0, 0)).toBe(12)
        expect(drawnRows(2000, 0, 0)).toBe(page)
    })

    it('draws the rows a fold asked for, never more than there are', () => {
        expect(drawnRows(2000, page + more, 0)).toBe(page + more)
        expect(drawnRows(page + 10, page + more, 0)).toBe(page + 10)
    })

    it('draws on through a row the page was asked to show, past the rows asked for', () => {
        expect(drawnRows(2000, 0, 1500)).toBe(1500)
        expect(drawnRows(2000, page + more, 10)).toBe(page + more)
    })
})

describe('moreLabel', () => {
    it("says how many rows or calls a fold holds back, and how many its step draws, in the diff's words", () => {
        expect(moreLabel(1, 'rows')).toBe('Show 1 more row')
        expect(moreLabel(60, 'calls')).toBe('Show 60 more calls')
        expect(moreLabel(1800, 'rows')).toBe(`Show ${TRANSCRIPT_BUDGET.step} of 1,800 more rows`)
    })
})
