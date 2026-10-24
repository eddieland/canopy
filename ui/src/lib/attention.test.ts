import { describe, expect, it } from 'vitest'

import { mockTickets } from '@/api/mocks'
import type { AttentionItem } from '@/api/types'

import {
    ask,
    blocking,
    breakdown,
    breakdownText,
    bySeverity,
    commandOf,
    countBySeverity,
    feedbackPlanOf,
    feedbackPlanReview,
    nextWaiting,
    pullRequestOf,
    reviewOf,
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
    task: null,
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
        expect(severity(item('a', 'disk_low', '2026-10-08T12:00:00Z'))).toBe('failed')
        // A run refused its model is stalled until the operator chooses another, ranked above a missing clone.
        expect(severity(item('a', 'model_missing', '2026-10-08T12:00:00Z'))).toBe('failed')
        expect(severity(item('a', 'model_list_failed', '2026-10-08T12:00:00Z'))).toBe('failed')
        expect(severity(item('a', 'awaiting_reply', '2026-10-08T12:00:00Z'))).toBe('waiting')
        expect(severity(item('a', 'untrusted_review', '2026-10-08T12:00:00Z'))).toBe('waiting')
        expect(severity(item('a', 'untrusted_artifact_comment', '2026-10-08T12:00:00Z'))).toBe('waiting')
        expect(severity(item('a', 'drafts_waiting', '2026-10-08T12:00:00Z'))).toBe('waiting')
        expect(severity(item('a', 'plan_review', '2026-10-08T12:00:00Z'))).toBe('waiting')
        expect(severity(item('a', 'review_waiting', '2026-10-08T12:00:00Z'))).toBe('waiting')
        expect(severity(item('a', 'review_unsettled', '2026-10-08T12:00:00Z'))).toBe('waiting')
        expect(severity(item('a', 'review_rebuttal', '2026-10-08T12:00:00Z'))).toBe('waiting')
        expect(severity(item('a', 'review_late', '2026-10-08T12:00:00Z'))).toBe('waiting')
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

// Nothing answered yet.
const none = () => false

describe('nextWaiting', () => {
    const T = '2026-10-08T11:00:00Z'
    const list = [
        item('broke', 'worker_failed', T),
        item('plan', 'plan_review', T),
        item('asked', 'awaiting_reply', T),
        item('untrusted', 'untrusted_review', T),
        item('review', 'needs_reviewer', T),
    ]
    it('moves on to the next item that waits on the operator, past what does not', () => {
        expect(nextWaiting(list, 'asked', none)?.id).toBe('untrusted')
        expect(nextWaiting(list, 'broke', none)?.id).toBe('plan')
    })

    it('searches on from the top once past the end', () => {
        expect(nextWaiting(list, 'untrusted', none)?.id).toBe('plan')
    })

    it('leaves out what the operator answered already, and finds nothing when nothing else waits', () => {
        expect(nextWaiting(list, 'asked', (i) => i.id === 'untrusted')?.id).toBe('plan')
        expect(nextWaiting(list, 'asked', (i) => i.id !== 'asked')).toBeNull()
        expect(nextWaiting([item('asked', 'awaiting_reply', T)], 'asked', none)).toBeNull()
    })

    it('starts from the top when the item answered is no longer listed', () => {
        expect(nextWaiting(list, 'gone', none)?.id).toBe('plan')
    })
})

describe('breakdown', () => {
    it('says the count in one set of words, most severe first, a finding as other', () => {
        const parts = breakdown({ failed: 1, waiting: 1, other: 2, finding: 1 })
        expect(parts.map((p) => p.kind)).toEqual(['failed', 'waiting', 'other'])
        expect(breakdownText(parts)).toBe('1 broken, 1 waiting on you, 3 other')
    })

    it('leaves out a part with nothing in it', () => {
        expect(breakdownText(breakdown({ failed: 0, waiting: 2, other: 0, finding: 0 }))).toBe('2 waiting on you')
        expect(breakdown({ failed: 0, waiting: 0, other: 0, finding: 0 })).toEqual([])
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
        expect(ask(item('a', 'untrusted_artifact_comment', at))).toBe('reply')
        expect(ask(item('a', 'plan_review', at))).toBe('plan')
        expect(ask(item('a', 'drafts_waiting', at))).toBe('drafts')
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

    it("leads a ticket's run refused its model to the ticket's models, and any other to `canopy models`", () => {
        const missing = {
            ...item('ABC-1', 'model_missing', at),
            detail:
                "OpenCode does not list the model acme/gone-1 chosen for ABC-1's worker runs (`canopy model ABC-1`), " +
                'so a run on it would fail before its first call',
        }
        expect(ask(missing)).toBe('model')
        expect(ask({ ...missing, reason: 'model_list_failed' })).toBe('model')
        // The overseer's or a chore's: no ticket's menu fixes it, so the command that says what the runtime lists.
        const overseer = { ...item('-', 'model_list_failed', at), ticket_key: null, detail: 'could not look it up' }
        expect(ask(overseer)).toBe('command')
        expect(commandOf(overseer)).toBe('canopy models')
        expect(ask({ ...overseer, chore: 'deps' })).toBe('command')
        expect(commandOf({ ...overseer, reason: 'model_missing' })).toBe('canopy models')
        // A chore's finding that happens to share the reason is a finding still.
        expect(ask({ ...overseer, chore: 'deps', finding: true })).toBe('none')
    })

    it("leads a task's item to the task's page, not to the commands its detail names", () => {
        const task = {
            ...item('task:4', 'awaiting_reply', at),
            ticket_key: null,
            task: 4,
            detail: "task:4's run 12 asked you a question, message 7: read it with `canopy show task:4`",
        }
        expect(ask(task)).toBe('task')
        expect(ask({ ...task, reason: 'task_ticket_unrecorded' })).toBe('task')
    })
})

describe("a feedback plan's review", () => {
    const at = '2026-10-08T12:00:00Z'
    const [ticket] = mockTickets
    if (!ticket) {
        throw new Error('fixtures are empty')
    }
    const waiting = { id: 3, pr_urls: ['https://github.com/acme/web/pull/88'], items: 2, stale: false }
    const review = item('ABC-102', 'plan_review', at)

    it('is told from a ticket plan by the plan its detail names, waiting or answered', () => {
        const named = {
            ...review,
            detail: 'feedback plan 3 for https://github.com/acme/web/pull/88 waits: canopy plan ABC-102 --approve',
        }
        expect(ask(named)).toBe('feedback-plan')
        expect(ask(named, ticket)).toBe('feedback-plan')
        expect(feedbackPlanOf(named)).toBe(3)
        expect(feedbackPlanReview(named, ticket)).toBe(true)
        expect(feedbackPlanOf({ ...named, reason: 'drafts_waiting' })).toBeNull()
        const plan = { ...review, detail: 'plan 2 waits: canopy show ABC-102, then canopy plan ABC-102 --approve' }
        expect(feedbackPlanOf(plan)).toBeNull()
        expect(ask(plan, ticket)).toBe('plan')
    })

    it("is told by the ticket's waiting feedback plan when its detail names none, unless its own plan waits", () => {
        expect(ask(review, { ...ticket, feedback_plan: waiting })).toBe('feedback-plan')
        expect(ask(review, { ...ticket, feedback_plan: waiting, plan_waits: true })).toBe('plan')
        expect(ask(review, { ...ticket, plan_waits: true })).toBe('plan')
    })
})

describe("a review's draft", () => {
    const at = '2026-10-08T12:00:00Z'
    const pr = 'https://github.com/acme/api/pull/14'
    const review = (reason: string, detail: string): AttentionItem => ({
        ...item(`pr:${pr}`, reason, at),
        ticket_key: null,
        pr,
        detail,
    })

    it("leads to the review's page, the run its detail names", () => {
        const waiting = review(
            'review_waiting',
            `review:5, which you asked for, is done: its draft of ${pr} waits on you to publish or stage it`,
        )
        expect(ask(waiting)).toBe('review')
        expect(reviewOf(waiting)).toBe(5)
        const staged = review('review_unsettled', `review:12's draft is in the review you staged on ${pr}`)
        expect(ask(staged)).toBe('review')
        expect(reviewOf(staged)).toBe(12)
    })

    it('asks for nothing of its own when its detail names no review, nor reads one out of a word', () => {
        expect(ask(review('review_waiting', `a draft of ${pr} waits`))).toBe('none')
        expect(reviewOf(review('review_waiting', 'prereview:5 and review:x'))).toBeNull()
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

    it("is the PR's own URL when the detail links into it, such as to a thread", () => {
        const at = '2026-10-08T12:00:00Z'
        const detail = 'see https://github.com/acme/web/pull/88#discussion_r123'
        expect(pullRequestOf({ ...item('a', 'needs_reviewer', at), detail })).toBe(
            'https://github.com/acme/web/pull/88',
        )
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
