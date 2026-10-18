import { describe, expect, it } from 'vitest'

import type { AttentionItem } from '@/api/types'

import {
    ask,
    blocking,
    breakdown,
    breakdownText,
    bySeverity,
    commandOf,
    countBySeverity,
    pullRequestOf,
    severity,
    shownDetail,
} from './attention'

const item = (id: string, reason: string, since: string, finding = false): AttentionItem => ({
    id,
    subject: id,
    ticket_key: finding ? null : id,
    ticket_title: null,
    chore: finding ? 'deps' : null,
    repo: null,
    reason,
    detail: '',
    since,
    finding,
    pr: null,
})

describe('blocking', () => {
    it('is anything that holds work up, not a PR waiting on a reviewer or its merge, nor a finding', () => {
        expect(blocking(item('a', 'worker_failed', '2026-10-08T12:00:00Z'))).toBe(true)
        expect(blocking(item('a', 'awaiting_reply', '2026-10-08T12:00:00Z'))).toBe(true)
        expect(blocking(item('a', 'needs_author', '2026-10-08T12:00:00Z'))).toBe(true)
        expect(blocking(item('a', 'repo_missing', '2026-10-08T12:00:00Z'))).toBe(true)
        expect(blocking(item('a', 'needs_reviewer', '2026-10-08T12:00:00Z'))).toBe(false)
        expect(blocking(item('a', 'ready_to_merge', '2026-10-08T12:00:00Z'))).toBe(false)
        expect(blocking(item('a', 'lodash-advisory', '2026-10-08T12:00:00Z', true))).toBe(false)
    })
})

describe('countBySeverity', () => {
    it('counts each severity, zero for one with no item', () => {
        const items = [
            item('a', 'worker_failed', '2026-10-08T12:00:00Z'),
            item('b', 'awaiting_reply', '2026-10-08T12:00:00Z'),
            item('c', 'untrusted_review', '2026-10-08T12:00:00Z'),
            item('d', 'needs_reviewer', '2026-10-08T12:00:00Z'),
        ]
        expect(countBySeverity(items)).toEqual({ failed: 1, waiting: 2, other: 1, finding: 0 })
    })
})

describe('severity', () => {
    it('ranks broken work, then what waits on the operator, then the rest, then findings', () => {
        expect(severity(item('a', 'worker_failed', '2026-10-08T12:00:00Z'))).toBe('failed')
        expect(severity(item('a', 'review_limit', '2026-10-08T12:00:00Z'))).toBe('failed')
        expect(severity(item('a', 'canopy_unavailable', '2026-10-08T12:00:00Z'))).toBe('failed')
        expect(severity(item('a', 'awaiting_reply', '2026-10-08T12:00:00Z'))).toBe('waiting')
        expect(severity(item('a', 'untrusted_review', '2026-10-08T12:00:00Z'))).toBe('waiting')
        expect(severity(item('a', 'plan_review', '2026-10-08T12:00:00Z'))).toBe('waiting')
        expect(severity(item('a', 'needs_reviewer', '2026-10-08T12:00:00Z'))).toBe('other')
        expect(severity(item('a', 'repo_missing', '2026-10-08T12:00:00Z'))).toBe('other')
        // A finding's reason is the chore's own id, which may collide with a ticket reason: it is a finding first.
        expect(severity(item('a', 'worker_failed', '2026-10-08T12:00:00Z', true))).toBe('finding')
    })
})

describe('bySeverity', () => {
    it('puts the most severe first, and within a severity the one open longest', () => {
        const sorted = bySeverity([
            item('finding', 'lodash-advisory', '2026-10-08T08:00:00Z', true),
            item('review', 'needs_reviewer', '2026-10-08T11:00:00Z'),
            item('question', 'awaiting_reply', '2026-10-08T11:56:00Z'),
            item('newer-failure', 'crashed', '2026-10-08T11:50:00Z'),
            item('older-failure', 'worker_failed', '2026-10-08T10:50:00Z'),
        ])
        expect(sorted.map((i) => i.id)).toEqual(['older-failure', 'newer-failure', 'question', 'review', 'finding'])
    })
})

describe('breakdown', () => {
    it('says the count in one set of words, most severe first, a finding as other', () => {
        const parts = breakdown({ failed: 1, waiting: 1, other: 2, finding: 1 })
        expect(parts.map((p) => p.kind)).toEqual(['failed', 'waiting', 'other'])
        expect(breakdownText(parts)).toBe('1 broken, 1 waiting on you, 3 other')
    })

    it('leaves out a part with nothing in it, and says nothing for an empty list', () => {
        expect(breakdownText(breakdown({ failed: 0, waiting: 2, other: 0, finding: 0 }))).toBe('2 waiting on you')
        expect(breakdownText(breakdown({ failed: 0, waiting: 0, other: 0, finding: 0 }))).toBe('nothing')
    })
})

describe('ask', () => {
    const at = '2026-10-08T12:00:00Z'
    it("picks a ticket's first block by its reason", () => {
        for (const reason of ['worker_failed', 'crashed', 'unpushed', 'unknown_result', 'attempt_limit']) {
            expect(ask(item('a', reason, at))).toBe('run')
        }
        expect(ask(item('a', 'needs_reviewer', at))).toBe('pull-request')
        expect(ask(item('a', 'ready_to_merge', at))).toBe('pull-request')
        expect(ask(item('a', 'awaiting_reply', at))).toBe('reply')
        expect(ask(item('a', 'untrusted_review', at))).toBe('reply')
        expect(ask(item('a', 'plan_review', at))).toBe('plan')
        expect(ask(item('a', 'memory_proposal', at))).toBe('memory')
        expect(ask({ ...item('a', 'lesson_review', at), ticket_key: null })).toBe('memory')
        // A reason that asks for nothing in particular leads with the ticket's own actions.
        expect(ask(item('a', 'needs_author', at))).toBe('ticket')
    })

    it('gives an item about nothing canopy shows its command, when its detail names one', () => {
        const missing = {
            ...item('api', 'repo_missing', at),
            ticket_key: null,
            repo: 'api',
            detail: 'repos/api has no clone; run `canopy workspace sync` in /work',
        }
        expect(ask(missing)).toBe('command')
        expect(commandOf(missing)).toBe('canopy workspace sync')
        expect(ask({ ...missing, detail: 'repos/api has no clone' })).toBe('none')
        expect(commandOf({ ...missing, detail: 'run `git fetch`' })).toBeNull()
        // A chore's item has its notes to show, whatever its detail names.
        expect(ask({ ...missing, chore: 'deps', detail: 'run `canopy show chore:deps`' })).toBe('none')
    })
})

describe('pullRequestOf', () => {
    it('is the first PR the detail names outside code, or null', () => {
        const pr = 'https://github.com/acme/web/pull/88'
        const at = '2026-10-08T12:00:00Z'
        expect(pullRequestOf({ ...item('a', 'needs_reviewer', at), detail: `${pr} waits on a reviewer` })).toBe(pr)
        expect(pullRequestOf({ ...item('a', 'needs_reviewer', at), detail: `see \`${pr}\`` })).toBeNull()
        expect(pullRequestOf({ ...item('a', 'needs_reviewer', at), detail: 'https://ci.example.test/7' })).toBeNull()
    })
})

describe('shownDetail', () => {
    it("drops the CLI's `canopy reply` hint, since the page's form is the answer, and keeps the rest", () => {
        const question = {
            ...item('ABC-102', 'awaiting_reply', '2026-10-08T12:00:00Z'),
            detail: 'message 5: Red or blue?; answer with `canopy reply ABC-102`',
        }
        expect(shownDetail(question)).toBe('message 5: Red or blue?')
        expect(shownDetail({ ...question, detail: 'run `canopy reply ABC-1` first' })).toBe(
            'run `canopy reply ABC-1` first',
        )
    })
})
