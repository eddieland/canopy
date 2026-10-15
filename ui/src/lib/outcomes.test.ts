import { describe, expect, it } from 'vitest'

import {
    dismissedText,
    forgotText,
    grantedText,
    notedText,
    reloadedText,
    repliedText,
    reviewDismissedText,
    reviewSentText,
    startedText,
    stoppedText,
} from './outcomes'

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
        expect(reloadedText({ changed: [], restart: [], after_tick: false })).toBe(
            'Nothing changed. The loop runs on it from now on.',
        )
        expect(reloadedText({ changed: ['capacity.max_workers'], restart: [], after_tick: true })).toBe(
            'capacity.max_workers changed. The loop reads it again once the running tick ends.',
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
        expect(grantedText('A-1', { kind: 'fix-ci', repo: 'web', runs: 2, limit: 3 })).toBe(
            'A-1 in web has had 2 fix-ci runs, and may now have 3. The next tick decides whether to dispatch it.',
        )
        expect(grantedText('https://example.test/o/r/pull/1', { kind: 'review', repo: null, runs: 3, limit: 4 })).toBe(
            'https://example.test/o/r/pull/1 has had 3 review runs, and may now have 4. ' +
                'The next tick decides whether to review it.',
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

    it('say whether a reply was new', () => {
        expect(repliedText('A-1', { message_id: 9, answers: 5, new: true })).toBe(
            'Recorded message 9 on A-1, answering message 5. The next tick reads it.',
        )
        expect(repliedText('A-1', { message_id: 9, answers: null, new: false })).toBe(
            'Message 9 on A-1 already says this; nothing new recorded.',
        )
    })
})
