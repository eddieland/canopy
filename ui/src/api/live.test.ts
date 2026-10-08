import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { applyStreamEvent, parseStreamEvent } from './live'
import { mockAttention, mockRuns, mockTickets } from './mocks'
import { keys } from './queries'
import type { Run, TicketDetail } from './types'

describe('applyStreamEvent', () => {
    it('replaces each list whole', () => {
        const client = new QueryClient()
        client.setQueryData(keys.runs, mockRuns)
        const [first] = mockRuns
        if (!first) throw new Error('fixtures are empty')

        applyStreamEvent(client, { type: 'runs.updated', runs: [{ ...first, state: 'stopped' }] })
        applyStreamEvent(client, { type: 'attention.updated', items: mockAttention })
        applyStreamEvent(client, { type: 'tickets.updated', tickets: mockTickets })

        expect(client.getQueryData<Run[]>(keys.runs)).toHaveLength(1)
        expect(client.getQueryData<Run[]>(keys.runs)?.[0]?.state).toBe('stopped')
        expect(client.getQueryData(keys.attention)).toEqual(mockAttention)
        expect(client.getQueryData(keys.tickets)).toEqual(mockTickets)
    })

    it('marks a changed ticket stale and leaves the others alone', () => {
        const client = new QueryClient()
        const detail = { ticket: mockTickets[0], units: [], runs: [], messages: [] } as unknown as TicketDetail
        client.setQueryData(keys.ticket('ABC-102'), detail)
        client.setQueryData(keys.ticket('ABC-999'), detail)

        applyStreamEvent(client, { type: 'ticket.changed', key: 'ABC-102' })

        expect(client.getQueryState(keys.ticket('ABC-102'))?.isInvalidated).toBe(true)
        expect(client.getQueryState(keys.ticket('ABC-999'))?.isInvalidated).toBe(false)
    })
})

describe('parseStreamEvent', () => {
    it('accepts known events and drops anything else', () => {
        const event = { type: 'runs.updated', runs: mockRuns }
        expect(parseStreamEvent(JSON.stringify(event))).toEqual(event)
        expect(parseStreamEvent('{"type":"ticket.changed","key":"ABC-1"}')).toEqual({
            type: 'ticket.changed',
            key: 'ABC-1',
        })
        expect(parseStreamEvent('not json')).toBeNull()
        expect(parseStreamEvent('{"type":"lease.updated","lease":{}}')).toBeNull()
        expect(parseStreamEvent('{"type":"runs.updated"}')).toBeNull()
        expect(parseStreamEvent('{"type":"runs.updated","runs":{}}')).toBeNull()
        expect(parseStreamEvent('{"type":"ticket.changed","key":7}')).toBeNull()
        expect(parseStreamEvent('null')).toBeNull()
    })
})
