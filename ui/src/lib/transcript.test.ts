import { describe, expect, it } from 'vitest'

import type { TranscriptEntry, TranscriptStep, TranscriptTool } from '@/api/types'

import {
    byCall,
    callLine,
    duration,
    elapsed,
    findQueryOf,
    hitsIn,
    outcome,
    pretty,
    runTokens,
    sentTokens,
    shownOutput,
    startOf,
    summary,
    tally,
    tokenCount,
    tokensCell,
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
        expect([tokenCount(950), tokenCount(12_340), tokenCount(1_240_000)]).toEqual(['950', '12.3k', '1.2M'])
    })
})

describe('runTokens', () => {
    it('reads as the CLI says it, the peak only when it was recorded', () => {
        expect(runTokens(3460, 9000)).toBe(', 3.5k new tokens, 9.0k peak context')
        expect(runTokens(3460, null)).toBe(', 3.5k new tokens')
        expect(runTokens(null, null)).toBe('')
    })
})

describe('tokensCell', () => {
    it('names what it counts, and is a dash when nothing reported one', () => {
        expect([tokensCell(3460, 'new'), tokensCell(9000, 'peak')]).toEqual(['3.5k new', '9.0k peak'])
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
