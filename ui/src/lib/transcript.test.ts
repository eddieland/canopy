import { describe, expect, it } from 'vitest'

import type { TranscriptEntry, TranscriptTool } from '@/api/types'

import { duration, elapsed, outcome, pretty, startOf, summary, tally, tokenCount } from './transcript'

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
    ...fields,
})

const shell = (command: string, output: string): TranscriptTool =>
    tool('completed', { input: JSON.stringify({ command, description: 'what the agent said' }), output })

describe('tally and startOf', () => {
    const entries: TranscriptEntry[] = [
        { kind: 'text', at: null, text: 'hi', reasoning: false, cut: false },
        tool('completed'),
        tool('error'),
        shell('canopy dispatch ABC-1', 'Error: dispatch refused (capacity): 2 of 2 running'),
        { kind: 'step', at: '2026-10-08T10:32:00Z', reason: 'stop', cost_usd: 0.1, tokens: 10 },
        { kind: 'error', at: null, name: 'APIError', message: '' },
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
})
