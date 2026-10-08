import { describe, expect, it } from 'vitest'

import { repliedText, startedText, stoppedText } from './outcomes'

describe('outcomes', () => {
    it('say what a start did, as canopy start does', () => {
        expect(startedText('A-1', { already: false, running_run: null, running_private: null })).toBe(
            'A-1 is started, privately: workers read it and write nothing to it. The next tick picks it up.',
        )
        expect(startedText('A-1', { already: true, running_run: 4, running_private: false })).toContain(
            'Run 4 (public, dispatched before this start, so it may write to the ticket) is still working it.',
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

    it('say whether a reply was new', () => {
        expect(repliedText('A-1', { message_id: 9, answers: 5, new: true })).toBe(
            'Recorded message 9 on A-1, answering message 5. The next tick reads it.',
        )
        expect(repliedText('A-1', { message_id: 9, answers: null, new: false })).toBe(
            'Message 9 on A-1 already says this; nothing new recorded.',
        )
    })
})
