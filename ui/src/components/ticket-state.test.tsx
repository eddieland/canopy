import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { TicketSummary } from '@/api/types'

import { TicketState } from './ticket-state'

afterEach(() => {
    cleanup()
})

/** What the cell reads for a ticket standing as `ticket` says. */
function shown(ticket: Pick<TicketSummary, 'running_run' | 'awaiting' | 'done'>) {
    const { container, unmount } = render(<TicketState ticket={ticket} />)
    const text = container.textContent
    unmount()
    return text
}

describe('TicketState', () => {
    it('names the run working the ticket and the question waiting on the operator', () => {
        expect(shown({ running_run: 41, awaiting: null, done: false })).toBe('run:41')
        expect(shown({ running_run: null, awaiting: 7, done: false })).toBe('waiting on you')
        expect(shown({ running_run: 41, awaiting: 7, done: false })).toBe('run:41waiting on you')
    })

    it('says open or done for a ticket with nothing working it or waiting, never nothing', () => {
        expect(shown({ running_run: null, awaiting: null, done: false })).toBe('open')
        expect(shown({ running_run: null, awaiting: null, done: true })).toBe('done')
    })
})
