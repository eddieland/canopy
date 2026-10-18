import { describe, expect, it } from 'vitest'

import type { Message } from '@/api/types'

import { sinceForget } from './forgotten'

const messages = [1, 2, 5].map((id) => ({ id }) as Message)

describe('sinceForget', () => {
    it('keeps every message of a ticket never forgotten', () => {
        expect(sinceForget({ messages, forgotten_message_id: null })).toEqual(messages)
    })

    it('keeps only the messages after the newest one the forget left behind', () => {
        expect(sinceForget({ messages, forgotten_message_id: 2 }).map((m) => m.id)).toEqual([5])
        expect(sinceForget({ messages, forgotten_message_id: 5 })).toEqual([])
    })
})
