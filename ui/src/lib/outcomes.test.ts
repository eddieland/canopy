import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'
import { draft } from '@/api/mocks'
import { DEFAULT_CLOCK } from '@/lib/clock'
import { localTime } from '@/lib/time'

import {
    dismissedText,
    draftDroppedText,
    draftEditedText,
    draftsSentText,
    draftsSentToast,
    draftsStagedText,
    draftsStagedToast,
    editedText,
    failedText,
    forgotText,
    grantedText,
    memoryForgottenText,
    notedText,
    planText,
    noticeSetText,
    promotedText,
    rejectedText,
    reloadedText,
    renewedText,
    repliedText,
    reviewDismissedText,
    reviewRequestedText,
    reviewSentText,
    reviewStoppedText,
    startedText,
    stoppedText,
    triedText,
} from './outcomes'

describe('failedText', () => {
    it("says a refusal's reason and the server's own words as they are", () => {
        expect(failedText(new ApiError(409, { guard: 'not_started', reason: 'ABC-1 was not started' }))).toBe(
            'ABC-1 was not started',
        )
        expect(failedText(new ApiError(503, 'the journal is busy'))).toBe('the journal is busy')
    })

    it('says whether an action was done when the server gave only its status', () => {
        expect(failedText(new ApiError(500, undefined))).toBe('canopy failed (500): it may not have been done')
        expect(failedText(new ApiError(502, { unexpected: true }))).toBe(
            'canopy failed (502): it may not have been done',
        )
        expect(failedText(new ApiError(404, undefined))).toBe('canopy answered 404: nothing was done')
    })

    it('says canopy did not answer, never the browser’s words, when no answer came', () => {
        const words = 'canopy did not answer: is `canopy loop` running?'
        expect(failedText(new TypeError('Failed to fetch'))).toBe(words)
        expect(failedText(new DOMException('The operation was aborted.', 'AbortError'))).toBe(words)
    })

    it('says any other error in its own words, or that the request failed', () => {
        expect(failedText(new Error('a review limit names its PR'))).toBe('a review limit names its PR')
        expect(failedText('no network')).toBe('no network')
        expect(failedText({ unexpected: true })).toBe('the request failed')
    })
})

describe('outcomes', () => {
    it('say what a start did, as canopy start does', () => {
        expect(startedText('A-1', { already: false, running_run: null, running_private: null })).toBe(
            'A-1 is started, privately: workers read it and write nothing to it. The next tick picks it up.',
        )
        expect(startedText('A-1', { already: true, running_run: 4, running_private: false })).toContain(
            'Run 4 (public, dispatched before this start, so it may write to the ticket) is still working it.',
        )
    })

    it('say what a reload found, when the loop runs on it, and what waits for a restart', () => {
        const notice = { text: 'CI is down.', since: '2026-10-08T11:50:00Z', lapses_at: '2026-10-08T15:50:00Z' }
        expect(
            noticeSetText({
                already: false,
                loop: { paused: null, notice: { ...notice, channel: 'web' }, memory: null },
            }),
        ).toBe('Notice set: runs dispatched from now on hear it until it lapses. The loop ticks soon.')
        const unchanged = 'Nothing changed: the config files say what the loop already runs on.'
        expect(reloadedText({ changed: [], restart: [], after_tick: false })).toBe(unchanged)
        // A running tick delays nothing when there is nothing to apply.
        expect(reloadedText({ changed: [], restart: [], after_tick: true })).toBe(unchanged)
        expect(reloadedText({ changed: ['capacity.max_workers'], restart: [], after_tick: false })).toBe(
            'capacity.max_workers changed. The loop runs on the new config now.',
        )
        expect(reloadedText({ changed: ['capacity.max_workers'], restart: [], after_tick: true })).toBe(
            'capacity.max_workers changed. The loop runs on the new config once the running tick ends.',
        )
        expect(
            reloadedText({
                changed: ['serve.port', 'serve.bind'],
                restart: ['serve.port', 'serve.bind'],
                after_tick: false,
            }),
        ).toContain('serve.port, serve.bind take effect on a restart.')
        expect(reloadedText({ changed: ['serve.port'], restart: ['serve.port'], after_tick: false })).toContain(
            'serve.port takes effect on a restart.',
        )
    })

    it('say what a stop did, with and without now', () => {
        expect(stoppedText('A-1', { already: false, running_run: 4, ended: false }, false)).toContain(
            'Run 4 is still working it and will finish.',
        )
        expect(stoppedText('A-1', { already: true, running_run: 4, ended: true }, true)).toBe(
            'A-1 was already stopped; nothing dispatches it now. Run 4 was ended and its slots returned.',
        )
        expect(stoppedText('A-1', { already: true, running_run: 4, ended: false }, true)).toContain('had already ended')
    })

    it("say what a forget cleared, and that its PRs and branch are the operator's to close", () => {
        expect(forgotText('A-1', { branch: null, prs: [] })).toBe(
            'A-1 is forgotten: its next implement starts over on a new branch.',
        )
        const said = forgotText('A-1', { branch: 'agent/A-1-x', prs: ['https://example.test/pr/1'] })
        expect(said).toContain('canopy no longer tracks branch agent/A-1-x, https://example.test/pr/1.')
        expect(said).toContain('delete its branch on origin yourself')
    })

    it('say what a grant did, as canopy grant does: the runs so far still count', () => {
        expect(grantedText('A-1', { kind: 'resume', repo: 'web', runs: 2, limit: 3 })).toBe(
            'A-1 in web has had 2 resume runs, and may now have 3. The next tick decides whether to dispatch it.',
        )
        expect(grantedText('https://example.test/o/r/pull/1', { kind: 'review', repo: null, runs: 3, limit: 4 })).toBe(
            'https://example.test/o/r/pull/1 has had 3 review runs, and may now have 4. ' +
                'The next tick decides whether to review it.',
        )
    })

    it('say what a review request did, as canopy start URL --review and canopy stop URL do', () => {
        const pr = 'https://example.test/o/r/pull/12'
        const request = {
            created_at: '2026-10-15T12:00:00Z',
            channel: 'web',
            ended_at: null,
            end_reason: null,
            notes: null,
        }
        expect(reviewRequestedText(pr, { request, already: false })).toBe(
            `${pr} is requested for review. The next tick reviews its head, once.`,
        )
        expect(reviewRequestedText(pr, { request, already: true })).toBe(`${pr} was already requested for review.`)
        expect(reviewRequestedText(pr, { request, already: true }, true)).toBe(
            `${pr} was already requested for review. Its notes are replaced.`,
        )
        expect(reviewStoppedText(pr, { request, running_review: null })).toBe(
            `${pr}'s review request is stopped; nothing reviews it now.`,
        )
        expect(reviewStoppedText(pr, { request, running_review: 4 })).toBe(
            `${pr}'s review request is stopped; nothing reviews it now. ` +
                'Review run 4 of it is still running and will finish.',
        )
    })

    it('say what a note to a chore did, and that its next run reads it', () => {
        expect(notedText('deps', { message_id: 9, answers: null, new: true })).toBe(
            'Recorded message 9 on chore:deps. Its next run reads it.',
        )
        expect(notedText('deps', { message_id: 9, answers: null, new: false })).toBe(
            'Message 9 on chore:deps already says this; nothing new recorded.',
        )
    })

    it('say what a try started, as canopy chore try does', () => {
        expect(triedText({ chore: 'deps', run_id: 5 })).toBe(
            'chore try deps: recorded as chore run 5, running now. Its findings reach the attention list when it ends.',
        )
    })

    it('say what a dismissal did, as canopy dismiss does', () => {
        expect(dismissedText({ chore: 'deps', finding: 'lodash-advisory', dismissed: true })).toBe(
            'chore:deps lodash-advisory is dismissed: it is off the attention list until the chore stops reporting it.',
        )
        expect(dismissedText({ chore: 'deps', finding: 'lodash-advisory', dismissed: false })).toBe(
            'chore:deps lodash-advisory is listed again while the chore reports it.',
        )
    })

    it("say what a dismissal of a review's finding did", () => {
        expect(reviewDismissedText({ run: 4, finding: 2, dismissed: true })).toBe(
            'review:4 finding 2 is dismissed: no worker or tick acts on it.',
        )
        expect(reviewDismissedText({ run: 4, finding: 2, dismissed: false })).toBe(
            'review:4 finding 2 is no longer dismissed: a resume hands it to the worker again.',
        )
    })

    it('say where sent findings went, as canopy send does', () => {
        const sent = { run: 4, findings: [1, 3], ticket_key: 'ABC-099', message_id: 12, new: true }
        expect(reviewSentText(sent)).toBe(
            'review:4 findings 1, 3 went to ABC-099 as message 12: the next tick reads it as your go-ahead.',
        )
        expect(reviewSentText({ ...sent, new: false })).toBe(
            'review:4 findings 1, 3 already went to ABC-099 as message 12.',
        )
    })

    it('say what a verb on a draft did, as canopy draft does', () => {
        expect(draftEditedText(draft({ hash: 'abc123def456' }))).toBe(
            "Run 45's draft 1 is in your words now, hash abc123def456.",
        )
        expect(draftDroppedText(draft({ status: 'dropped' }))).toBe("Run 45's draft 1 is dropped.")
        const url = 'https://github.com/acme/web/pull/88#discussion_r1'
        expect(
            draftsSentText({
                posted: [draft({ status: 'sent', sent_url: url })],
                already: [draft({ number: 2, status: 'sent', sent_url: null })],
                failed: [{ draft: draft({ number: 3 }), why: 'the post failed: 502' }],
                unconfirmed: [draft({ number: 4, status: 'unconfirmed' })],
                staged: [draft({ number: 5, status: 'staged' })],
            }),
        ).toBe(
            `Sent run 45's draft 1: ${url}. Run 45's draft 2 was sent already. ` +
                "Run 45's draft 3 was not sent: the post failed: 502. Run 45's draft 4 may have been posted: the " +
                'post ended without saying. A read of its PR settles it; canopy sends it no other time. Staged run ' +
                "45's draft 5 in a review for you to submit on GitHub.",
        )
    })

    it('say what a stage did: each draft in the review, and each reaction that went on its comment now', () => {
        const none = { posted: [], already: [], failed: [], unconfirmed: [], staged: [] }
        expect(
            draftsStagedText({
                ...none,
                staged: [draft({ status: 'staged', reacted: 'heart' })],
                posted: [draft({ number: 2, status: 'sent', text: '', reacted: '+1' })],
                failed: [{ draft: draft({ number: 3 }), why: 'the post failed' }],
            }),
        ).toBe(
            "Staged run 45's draft 1 in a review for you to submit on GitHub. Run 45's draft 2 put thumbs up on its " +
                "comment now, not in the review: GitHub can't keep a reaction pending. Run 45's draft 1 put heart on " +
                "its comment now, not in the review: GitHub can't keep a reaction pending. Run 45's draft 3 was not " +
                'sent: the post failed.',
        )
    })

    it('toast a stage: how many drafts wait in the review, where to finish it, and the reactions added now', () => {
        const pr = 'https://github.com/acme/web/pull/88'
        const none = { posted: [], already: [], failed: [], unconfirmed: [], staged: [] }
        const two = [draft({ status: 'staged' }), draft({ number: 2, status: 'staged' })]
        expect(draftsStagedToast({ ...none, staged: two }, pr)).toEqual({
            title: 'Staged 2 drafts in a review on GitHub',
            detail: `${pr}/files`,
            tone: 'done',
        })
        const alone = draft({ number: 3, status: 'sent', text: '', reacted: '+1' })
        expect(draftsStagedToast({ ...none, staged: two, posted: [alone] }, pr)).toEqual({
            title: 'Staged 2 drafts in a review on GitHub, and added 1 reaction now',
            detail: `${pr}/files`,
            tone: 'done',
        })
        expect(draftsStagedToast({ ...none, posted: [alone] }, pr)).toEqual({
            title: 'Added 1 reaction now',
            tone: 'done',
        })
        expect(draftsStagedToast({ ...none, failed: [{ draft: draft(), why: 'refused' }] }, pr)).toEqual({
            title: 'Staged nothing',
            tone: 'failed',
        })
    })

    it("toast a send: the one draft's fate, or how many of several reached the PR, and where they went", () => {
        const url = 'https://github.com/acme/web/pull/88#pullrequestreview-1'
        const none = { posted: [], already: [], failed: [], unconfirmed: [], staged: [] }
        expect(draftsSentToast({ ...none, posted: [draft({ status: 'sent', sent_url: url })] })).toEqual({
            title: "Sent run 45's draft 1",
            detail: url,
            tone: 'done',
        })
        expect(draftsSentToast({ ...none, already: [draft({ status: 'sent', sent_url: null })] })).toEqual({
            title: "Run 45's draft 1 was sent already",
            tone: 'done',
        })
        expect(draftsSentToast({ ...none, failed: [{ draft: draft(), why: 'the post failed: 502' }] })).toEqual({
            title: "Run 45's draft 1 was not sent",
            tone: 'failed',
        })
        expect(draftsSentToast({ ...none, unconfirmed: [draft({ status: 'unconfirmed' })] })).toEqual({
            title: "Run 45's draft 1 may have been posted",
            tone: 'failed',
        })
        const two = [draft({ status: 'sent', sent_url: url }), draft({ number: 2, status: 'sent', sent_url: url })]
        expect(draftsSentToast({ ...none, posted: two })).toEqual({ title: 'Sent 2 drafts', detail: url, tone: 'done' })
        expect(
            draftsSentToast({
                ...none,
                posted: two,
                failed: [{ draft: draft({ number: 3 }), why: 'the post failed' }],
            }),
        ).toEqual({ title: 'Sent 2 of 3 drafts', detail: url, tone: 'failed' })
        expect(draftsSentToast({ ...none, failed: two.map((d) => ({ draft: d, why: 'the post failed' })) })).toEqual({
            title: '2 drafts not sent',
            tone: 'failed',
        })
    })

    it('say whether a reply was new', () => {
        expect(repliedText('A-1', { message_id: 9, answers: 5, new: true })).toBe(
            'Recorded message 9 on A-1, answering message 5. The next tick reads it.',
        )
        expect(repliedText('A-1', { message_id: 9, answers: null, new: false })).toBe(
            'Message 9 on A-1 already says this; nothing new recorded.',
        )
    })

    it('says what a word on a plan did, as `canopy plan` does', () => {
        expect(planText('PROJ-1', { action: 'approve', plan: 3, superseded: null, already: false, waived: null })).toBe(
            'Plan 3 of PROJ-1 is approved as its file stands now. The next tick can implement it.',
        )
        expect(planText('PROJ-1', { action: 'skip', plan: null, superseded: 3, already: false, waived: null })).toBe(
            "Plan 3 of PROJ-1 is superseded; its file stays. PROJ-1's plan is skipped: its implement goes ahead " +
                'without one.',
        )
        expect(
            planText('PROJ-1', { action: 'request', plan: null, superseded: null, already: true, waived: null }),
        ).toBe('PROJ-1 already waits on a plan: the next tick dispatches a planner if none is running.')
        expect(
            planText('PROJ-1', { action: 'request', plan: null, superseded: null, already: false, waived: null }),
        ).toContain('PROJ-1 is planned first')
    })

    it("says a word on a plan undid a triage's waiver, or put the operator's skip in its place", () => {
        const asked = { plan: null, superseded: null, already: false, waived: 7 }
        expect(planText('PROJ-1', { action: 'request', ...asked })).toBe(
            "Triage run 7 had waived PROJ-1's plan; it is undone. PROJ-1 is planned first: the next tick dispatches " +
                'a planner, and nothing is implemented until you approve its plan.',
        )
        expect(planText('PROJ-1', { action: 'skip', ...asked })).toBe(
            "Triage run 7 had waived PROJ-1's plan; your skip takes its place. PROJ-1's plan is skipped: its " +
                'implement goes ahead without one.',
        )
    })

    it('says what a verb on memory did, as `canopy memory` does', () => {
        const lesson = {
            id: 9,
            scope: 'lesson',
            ticket_key: null,
            repo: 'web',
            key: 'web-tests',
            text: 'Run the tests once.',
            status: 'active',
            why: null,
            run_id: null,
            head: null,
            created_at: '2026-10-08T12:00:00Z',
            use_count: 0,
            used_by: [] as number[],
            last_used_at: null,
            review_at: '2027-01-06T12:00:00Z',
            wrong_at: null,
            wrong_run_id: null,
            promoted_from: 2,
            origin: null,
            version: 1,
            edited: false,
            private: false,
        } as const
        const note = { ...lesson, id: 2, scope: 'ticket', ticket_key: 'ABC-1', repo: null, review_at: null } as const
        const due = localTime('2027-01-06T12:00:00Z', DEFAULT_CLOCK)
        expect(promotedText({ lesson, source: note, superseded: null, served: true, private: false })).toBe(
            `Note 2 is lesson 9 (\`web-tests\`) for web, due for review at ${due}. Every run dispatched from now on ` +
                'reads it.',
        )
        const recorded = promotedText({ lesson, source: note, superseded: 8, served: false, private: true })
        expect(recorded).toContain('It replaces lesson 8, under the same key.')
        expect(recorded).toContain("Warning: its text is from a private ticket's run")
        expect(recorded).toMatch(
            /It is recorded, not served: memory\.proposals is record, so no run reads it until it is use\.$/u,
        )
        const edit = {
            lesson: { ...lesson, id: 10, promoted_from: 9, version: 3, edited: true },
            replaced: { ...lesson, status: 'superseded' as const, why: 'edited into lesson 10' },
            served: true,
        }
        expect(editedText(edit)).toBe(
            `Lesson 9 is edited into lesson 10 (\`web-tests\`) for web, version 3, due for review at ${due}. ` +
                'Lesson 9 stays in its history. Every run dispatched from now on reads the new version.',
        )
        expect(editedText({ ...edit, served: false })).toMatch(
            /It is recorded, not served: memory\.proposals is record/u,
        )
        expect(rejectedText(5)).toBe('Proposal 5 is rejected.')
        expect(renewedText({ id: 9, review_at: '2027-01-06T12:00:00Z' })).toBe(
            `Lesson 9 is renewed: due for review at ${due}.`,
        )
        const forgot = { id: 9, scope: 'lesson', key: 'web-tests', checkpointed: true } as const
        expect(memoryForgottenText(forgot)).toBe('Memory 9 (lesson `web-tests`) is forgotten: its text is deleted.')
        expect(memoryForgottenText({ ...forgot, checkpointed: false })).toContain('may stay in the log')
    })
})
