import { describe, expect, it } from 'vitest'

import { dismissedText, forgotText, notedText, reloadedText, repliedText, startedText, stoppedText } from './outcomes'

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

    it('say whether a reply was new', () => {
        expect(repliedText('A-1', { message_id: 9, answers: 5, new: true })).toBe(
            'Recorded message 9 on A-1, answering message 5. The next tick reads it.',
        )
        expect(repliedText('A-1', { message_id: 9, answers: null, new: false })).toBe(
            'Message 9 on A-1 already says this; nothing new recorded.',
        )
    })
})
