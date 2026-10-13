import { describe, expect, it } from 'vitest'

import type { TranscriptEntry } from '@/api/types'

import { duration, elapsed, hint, startOf, tally, tokenCount } from './transcript'

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

const tool = (status: 'completed' | 'error'): TranscriptEntry => ({
    kind: 'tool',
    at: '2026-10-08T10:31:00Z',
    tool: 'bash',
    status,
    title: null,
    input: '{}',
    output: '',
    duration_ms: null,
    cut: false,
})

describe('tally and startOf', () => {
    const entries: TranscriptEntry[] = [
        { kind: 'text', at: null, text: 'hi', reasoning: false, cut: false },
        tool('completed'),
        tool('error'),
        { kind: 'step', at: '2026-10-08T10:32:00Z', reason: 'stop', cost_usd: 0.1, tokens: 10, split: null },
        { kind: 'error', at: null, name: 'APIError', message: '' },
    ]

    it('counts tool calls, failed ones, model calls, and errors', () => {
        expect(tally(entries)).toEqual({ tools: 2, failed: 1, calls: 1, errors: 1 })
    })

    it('starts at the first entry with a time', () => {
        expect(startOf(entries)).toBe('2026-10-08T10:31:00Z')
        expect(startOf([])).toBeNull()
    })
})

describe('hint', () => {
    it('is the first string value of the input, on one line', () => {
        expect(hint('{\n  "filePath": "/repo/src/a.ts",\n  "limit": 20\n}')).toBe('/repo/src/a.ts')
        expect(hint('{"limit": 20, "command": "npm  test\\n  -- search"}')).toBe('npm test -- search')
    })

    it('is empty for an input with no string, or one cut short', () => {
        expect(hint('{"limit": 20}')).toBe('')
        expect(hint('{"command": "np')).toBe('')
        expect(hint('[]')).toBe('')
    })
})
