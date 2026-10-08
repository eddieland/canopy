import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { applyStreamEvent, parseStreamEvent, upsert } from './live'
import { mockLeases, mockSessions } from './mocks'
import { keys } from './queries'
import type { Lease, Session } from './types'

describe('upsert', () => {
    it('replaces by id without mutating, and appends a new id', () => {
        const items = [
            { id: 'a', n: 1 },
            { id: 'b', n: 2 },
        ]
        const replaced = upsert(items, { id: 'b', n: 3 })
        expect(replaced).toEqual([
            { id: 'a', n: 1 },
            { id: 'b', n: 3 },
        ])
        expect(items[1]).toEqual({ id: 'b', n: 2 })
        expect(upsert(items, { id: 'c', n: 4 })?.map((i) => i.id)).toEqual(['a', 'b', 'c'])
    })

    it('leaves an unloaded list alone', () => {
        expect(upsert(undefined, { id: 'a' })).toBeUndefined()
    })
})

describe('applyStreamEvent', () => {
    it('writes sessions and leases into their query keys', () => {
        const client = new QueryClient()
        client.setQueryData(keys.sessions, mockSessions)
        client.setQueryData(keys.leases, mockLeases)
        const [first] = mockSessions
        const [lease] = mockLeases
        if (!first || !lease) throw new Error('fixtures are empty')

        applyStreamEvent(client, { type: 'session.updated', session: { ...first, state: 'failed' } })
        applyStreamEvent(client, { type: 'lease.updated', lease: { ...lease, state: 'expiring' } })

        expect(client.getQueryData<Session[]>(keys.sessions)?.[0]?.state).toBe('failed')
        expect(client.getQueryData<Session[]>(keys.sessions)).toHaveLength(mockSessions.length)
        expect(client.getQueryData<Lease[]>(keys.leases)?.[0]?.state).toBe('expiring')
    })
})

describe('parseStreamEvent', () => {
    it('accepts known events and drops anything else', () => {
        const event = { type: 'session.updated', session: mockSessions[0] }
        expect(parseStreamEvent(JSON.stringify(event))).toEqual(event)
        expect(parseStreamEvent('not json')).toBeNull()
        expect(parseStreamEvent('{"type":"ticket.updated","ticket":{}}')).toBeNull()
        expect(parseStreamEvent('{"type":"session.updated"}')).toBeNull()
        expect(parseStreamEvent('null')).toBeNull()
    })
})
