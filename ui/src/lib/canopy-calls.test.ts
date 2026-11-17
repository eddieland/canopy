import { describe, expect, it } from 'vitest'

import type { TranscriptTool } from '@/api/types'
import { canopyCall, commitsOf, diffLinesOf, matchesOf, reviewItemsOf } from '@/lib/canopy-calls'

// A call of the tool named `name` with `input`, which canopy answered `output`, or refused.
function call(name: string, input: unknown, output: unknown = '', status: TranscriptTool['status'] = 'completed') {
    return {
        kind: 'tool',
        at: null,
        tool: name,
        status,
        title: null,
        input: JSON.stringify(input),
        output: typeof output === 'string' ? output : JSON.stringify(output),
        duration_ms: null,
        cut: false,
        call: 1,
    } satisfies TranscriptTool
}

describe('canopyCall', () => {
    it('reads a dispatch as its ticket, its kind, where it works, and the run canopy recorded', () => {
        const input = {
            key: 'ABC-104',
            kind: 'implement',
            repos: ['web', 'api'],
            context: 'Start with the form.\nThen CI.',
        }
        const output = { key: 'ABC-104', kind: 'implement', dry_run: false, recorded: 43, branch: 'agent/ABC-104-sso' }
        expect(canopyCall(call('canopy_dispatch', input, output))).toEqual({
            subject: 'ABC-104',
            action: 'implement',
            tone: 'plain',
            detail: 'web, api',
            said: { label: 'context', text: 'Start with the form.\nThen CI.' },
            told: 'run 43 on agent/ABC-104-sso',
        })
        const dry = canopyCall(call('canopy_dispatch', input, { ...output, dry_run: true, recorded: null }))
        expect(dry?.told).toBe('dry run: nothing recorded')
    })

    it('says nothing canopy answered of a call it refused', () => {
        const refused = call('canopy_dispatch', { key: 'ABC-104', kind: 'implement' }, 'refused (running)', 'error')
        expect(canopyCall(refused)).toMatchObject({ subject: 'ABC-104', action: 'implement', told: null })
    })

    it('reads the overseer’s other calls: an attention item, a review, a chore', () => {
        const pr = 'https://github.com/acme/web/pull/88'
        expect(
            canopyCall(call('canopy_attention', { key: 'ABC-1', reason: 'needs_human', detail: 'Pick one.' })),
        ).toMatchObject({
            subject: 'ABC-1',
            action: 'needs_human',
            tone: 'blocked',
            said: { label: 'detail', text: 'Pick one.' },
        })
        const started = {
            pr,
            dry_run: false,
            reviews: [{ persona: 'security', recorded: 7 }],
            waits: { guard: 'capacity' },
        }
        const review = call('canopy_review-run', { pr, sha: '0123456789abcdef0123', ticket: 'ABC-1' }, started)
        expect(canopyCall(review)).toMatchObject({
            subject: 'acme/web#88',
            action: 'review',
            detail: 'at 0123456789 ABC-1',
            told: 'review 7 (security) · held: capacity',
        })
        expect(canopyCall(call('canopy_review_wait', { pr, rationale: 'Checks still run.' }))).toMatchObject({
            subject: 'acme/web#88',
            action: 'wait',
            said: { label: 'rationale', text: 'Checks still run.' },
        })
        expect(canopyCall(call('canopy_chore-run', { name: 'deps' }, { name: 'deps', recorded: 3 }))).toMatchObject({
            subject: 'deps',
            action: 'run',
            told: 'chore run 3',
        })
        expect(canopyCall(call('canopy_chore_history', { name: 'deps', limit: 5 }))?.detail).toBe('last 5')
    })

    it('reads a git call as a command would say it, and how much it found', () => {
        const diff = call('canopy_git_diff', {
            repo: 'web',
            base: 'main',
            head: 'HEAD',
            paths: ['src/a.ts'],
            stat: true,
        })
        expect(canopyCall(diff)).toMatchObject({ subject: 'web', action: 'stat', detail: 'main..HEAD -- src/a.ts' })
        const blame = call('canopy_git_blame', { rev: 'HEAD', path: 'src/a.ts', start: 10, end: 40 })
        expect(canopyCall(blame)?.detail).toBe('HEAD:src/a.ts L10-40')
        const grep = call(
            'canopy_git_grep',
            { rev: 'HEAD', text: '_MS =' },
            { files: [], matched_lines: 12, matched_files: 3, more: true },
        )
        expect(canopyCall(grep)).toMatchObject({ detail: '"_MS =" at HEAD', told: '12 lines in 3 files, and more' })
        const log = call('canopy_git_log', { range: 'main..HEAD' }, { commits: [{ commit: 'a' }], more: false })
        expect(canopyCall(log)?.told).toBe('1 commit')
        expect(canopyCall(call('canopy_reports_health', { days: 7 }))?.detail).toBe('7 days')
    })

    it('reads no other tool’s call, nor one of canopy’s it does not know', () => {
        expect(canopyCall(call('github_dispatch', { key: 'ABC-1', kind: 'implement' }))).toBeNull()
        expect(canopyCall(call('canopy_new-tool', { key: 'ABC-1' }))).toBeNull()
        expect(canopyCall(call('canopy_constructor', { key: 'ABC-1' }))).toBeNull()
        expect(canopyCall(call('canopy_dispatch', ['ABC-1']))).toBeNull()
    })
})

describe('what canopy answered, laid out', () => {
    it('reads the commits a log listed', () => {
        const commits = [
            {
                commit: 'abc123',
                author: 'Op',
                date: '2026-10-08T12:00:00Z',
                message: 'Fix it\n\nBody.',
                files: [{}, {}],
            },
        ]
        const entry = call('canopy_git_log', { range: 'main..HEAD' }, { commits, more: false })
        expect(commitsOf(entry)).toEqual([
            { commit: 'abc123', author: 'Op', date: '2026-10-08T12:00:00Z', subject: 'Fix it', files: 2 },
        ])
        expect(commitsOf(call('canopy_git_grep', {}, { commits }))).toBeNull()
        expect(commitsOf(call('canopy_git_log', {}, 'refused', 'error'))).toBeNull()
    })

    it('reads the files and lines a grep found', () => {
        const files = [{ path: 'a.ts', matched_lines: 1, lines: [{ line: 3, text: 'x = 1', match: true }] }]
        expect(matchesOf(call('canopy_git_grep', { text: 'x' }, { files }))).toEqual([
            { path: 'a.ts', matched: 1, lines: [{ line: 3, text: 'x = 1', match: true }] },
        ])
    })

    it('reads the review items a review-items call read', () => {
        const items = [
            { number: 4, item: 'comment', author: 'sam', trusted: false, worker: false, state: null, body: 'Why?' },
        ]
        expect(
            reviewItemsOf(call('canopy_review-items', { key: 'ABC-1', repo: 'web', numbers: [4] }, { items })),
        ).toEqual([
            { number: '4', item: 'comment', author: 'sam', trusted: false, worker: false, state: null, body: 'Why?' },
        ])
    })

    it('names each line of a diff, every character kept, and leaves a stat and another tool’s output plain', () => {
        const patch = [
            'diff --git a/a.ts b/a.ts',
            '--- a/a.ts',
            '+++ b/a.ts',
            '@@ -1,2 +1,2 @@',
            ' same',
            '-old',
            '+new',
        ]
        const lines = diffLinesOf(call('canopy_git_diff', { base: 'main', head: 'HEAD' }, patch.join('\n')))
        expect(lines?.map((line) => line.kind)).toEqual(['file', 'file', 'file', 'hunk', 'ctx', 'del', 'add'])
        expect(lines?.map((line) => line.text).join('\n')).toBe(patch.join('\n'))
        expect(diffLinesOf(call('canopy_git_diff', { base: 'a', head: 'b', stat: true }, ' a.ts | 2 +-'))).toBeNull()
        expect(diffLinesOf(call('bash', { command: 'git diff' }, patch.join('\n')))).toBeNull()
    })
})
