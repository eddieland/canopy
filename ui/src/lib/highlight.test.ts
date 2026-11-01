import { describe, expect, it, vi } from 'vitest'

import type { DiffHunk, DiffLine } from '@/api/types'
import { highlightHunks, highlightLines, kindOf } from '@/lib/highlight'
import type { CodeToken } from '@/lib/highlight'

// These tests read colors, which Shiki stops giving a line it has read for too long: a busy runner's (`untimedShiki`).
vi.mock(import('shiki/core'), async (importOriginal) =>
    (await import('@/test-utils')).untimedShiki(await importOriginal()),
)

// Lines without their numbers, which the highlighter never reads.
const ctx = (text: string): DiffLine => ({ kind: 'ctx', old: null, new: null, text })
const add = (text: string): DiffLine => ({ kind: 'add', old: null, new: null, text })
const del = (text: string): DiffLine => ({ kind: 'del', old: null, new: null, text })

// The pieces of a line of `kind`, to check a line's colors without spelling out every space.
const of = (tokens: CodeToken[] | undefined, kind: CodeToken['kind']) =>
    (tokens ?? []).filter((token) => token.kind === kind).map((token) => token.text.trim())

describe('highlightHunks', () => {
    it("colors a line's keywords, strings, constants, functions, and comments, its tokens spelling it", async () => {
        const hunk: DiffHunk = {
            header: '',
            lines: [ctx('def greet(name):'), add('    return f"hi {name}" * 2  # twice')],
        }
        const [lines] = await highlightHunks('python', [hunk])
        const [def, body] = lines ?? []
        expect(of(def, 'keyword')).toContain('def')
        expect(of(def, 'function')).toContain('greet')
        expect(of(body, 'keyword')).toContain('return')
        expect(of(body, 'constant')).toContain('2')
        expect(of(body, 'comment').join('')).toContain('twice')
        for (const [i, line] of hunk.lines.entries()) {
            expect(lines?.[i]?.map((token) => token.text).join('')).toBe(line.text)
        }
    })

    it('reads each side of a hunk whole, so a string across lines stays a string on both', async () => {
        const hunk: DiffHunk = {
            header: '',
            lines: [ctx('const a = `start'), del('removed line'), add('added line'), ctx('end`')],
        }
        const [lines] = await highlightHunks('typescript', [hunk])
        // In the template string on the side each is on, the deleted line on the old, the added on the new.
        expect(lines?.[1]).toEqual([{ kind: 'string', text: 'removed line' }])
        expect(lines?.[2]).toEqual([{ kind: 'string', text: 'added line' }])
        expect(of(lines?.[3], 'string').join('')).toContain('end')
    })

    it('reads a side longer than the grammar reads at once as if whole, a string open far down it', async () => {
        const inside = Array.from({ length: 450 }, (_, i) => add(`line ${i}`))
        const hunk: DiffHunk = {
            header: '',
            lines: [ctx('const a = `start'), ...inside, ctx('end`'), add('const b = 1')],
        }
        const [lines] = await highlightHunks('typescript', [hunk])
        expect(lines?.[400]).toEqual([{ kind: 'string', text: 'line 399' }])
        expect(of(lines?.at(-1), 'keyword')).toContain('const')
        expect(lines).toHaveLength(hunk.lines.length)
    })

    it('keeps the hunks and their lines in order, one entry per line', async () => {
        const hunks: DiffHunk[] = [
            { header: '', lines: [ctx('a = 1'), del('b = 2')] },
            { header: 'def f():', lines: [add('c = 3')] },
        ]
        const result = await highlightHunks('python', hunks)
        expect(result.map((lines) => lines.length)).toEqual([2, 1])
        expect(result[1]?.[0]?.map((token) => token.text).join('')).toBe('c = 3')
    })

    it('leaves a line plain when it is too long to be worth the grammar', async () => {
        const long = `x = "${'a'.repeat(3000)}"`
        const [lines] = await highlightHunks('python', [{ header: '', lines: [add(long), add('y = 1')] }])
        expect(lines?.[0]).toEqual([{ kind: 'text', text: long }])
        expect(of(lines?.[1], 'constant')).toContain('1')
    })
})

describe('highlightLines', () => {
    it("reads a code block whole, a line apiece, each line's tokens spelling it", async () => {
        const lines = ['# The loop', '[policy]', 'max_resume_attempts = 2', '', 'name = """', 'still a string', '"""']
        const tokens = await highlightLines('toml', lines)
        expect(tokens).toHaveLength(lines.length)
        expect(of(tokens[0], 'comment').join('')).toBe('# The loop')
        expect(of(tokens[2], 'constant')).toContain('2')
        // Read whole, so a string across lines stays a string on the line between.
        expect(tokens[5]).toEqual([{ kind: 'string', text: 'still a string' }])
        for (const [i, line] of lines.entries()) {
            expect(tokens[i]?.map((token) => token.text).join('')).toBe(line)
        }
    })
})

describe('kindOf', () => {
    it('names a token by its theme color, and anything the theme does not single out as text', () => {
        expect(kindOf('var(--syntax-token-keyword)')).toBe('keyword')
        expect(kindOf('var(--syntax-token-string-expression)')).toBe('string')
        expect(kindOf('var(--syntax-foreground)')).toBe('text')
        expect(kindOf(undefined)).toBe('text')
    })
})
