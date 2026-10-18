import { describe, expect, it } from 'vitest'

import type { Message, TicketForget } from '@/api/types'

import { attempts, sinceForget } from './forgotten'

const messages = [1, 2, 5, 6].map((id) => ({ id }) as Message)

function forgot(messageId: number | null): TicketForget {
    return { at: '2026-10-08T11:00:00Z', channel: 'cli', run_id: null, message_id: messageId, branch: null, prs: [] }
}

describe('sinceForget', () => {
    it('keeps every message of a ticket never forgotten', () => {
        expect(sinceForget({ messages, forgets: [] })).toEqual(messages)
    })

    it('keeps only the messages after the newest one the latest forget left behind', () => {
        expect(sinceForget({ messages, forgets: [forgot(1), forgot(5)] }).map((m) => m.id)).toEqual([6])
        expect(sinceForget({ messages, forgets: [forgot(6)] })).toEqual([])
        // A forget before any message was said leaves every message after it.
        expect(sinceForget({ messages, forgets: [forgot(null)] })).toEqual(messages)
    })
})

describe('attempts', () => {
    it('gives each forget the messages said since the one before it', () => {
        const found = attempts({ messages, forgets: [forgot(2), forgot(2), forgot(5)] })
        expect(found.map((a) => [a.number, a.messages.map((m) => m.id)])).toEqual([
            [1, [1, 2]],
            [2, []],
            [3, [5]],
        ])
    })

    it('gives a forget made before any message was said none', () => {
        expect(attempts({ messages, forgets: [forgot(null)] }).map((a) => a.messages)).toEqual([[]])
    })
})
