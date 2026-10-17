import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { applyStreamEvent, parseStreamEvent } from './live'
import { mockAttention, mockChores, mockRuns, mockTickets } from './mocks'
import { keys } from './queries'
import type { ChoreDetail, ChoreRunDetail, Run, TicketDetail } from './types'

describe('applyStreamEvent', () => {
    it('replaces each list whole', () => {
        const client = new QueryClient()
        client.setQueryData(keys.runs, mockRuns)
        const [first] = mockRuns
        if (!first) {
            throw new Error('fixtures are empty')
        }

        applyStreamEvent(client, { type: 'runs.updated', runs: [{ ...first, state: 'stopped' }] })
        applyStreamEvent(client, { type: 'attention.updated', items: mockAttention })
        applyStreamEvent(client, { type: 'tickets.updated', tickets: mockTickets })
        const spend = {
            day: { since: '2026-10-07T12:00:00Z', hours: 24, cost_usd: 2.5 },
            month: { since: '2026-09-08T12:00:00Z', hours: 720, cost_usd: 31.4 },
            total_usd: 120.75,
        }
        applyStreamEvent(client, { type: 'spend.updated', spend })
        applyStreamEvent(client, { type: 'tick.updated', tick: null, acknowledged: null })

        expect(client.getQueryData(keys.spend)).toEqual(spend)
        expect(client.getQueryData(keys.tick)).toEqual({ tick: null, acknowledged: null })
        expect(client.getQueryData<Run[]>(keys.runs)).toHaveLength(1)
        expect(client.getQueryData<Run[]>(keys.runs)?.[0]?.state).toBe('stopped')
        expect(client.getQueryData(keys.attention)).toEqual(mockAttention)
        expect(client.getQueryData(keys.tickets)).toEqual(mockTickets)
    })

    it("marks every window's spend breakdown stale on a spend or a tick, and keeps the spend's own data", () => {
        const client = new QueryClient()
        client.setQueryData(keys.spendBreakdown(7), { days: 7 })
        client.setQueryData(keys.spendBreakdown(30), { days: 30 })
        const spend = {
            day: { since: '2026-10-07T12:00:00Z', hours: 24, cost_usd: 2.5 },
            month: { since: '2026-09-08T12:00:00Z', hours: 720, cost_usd: 31.4 },
            total_usd: 120.75,
        }
        applyStreamEvent(client, { type: 'spend.updated', spend })
        expect(client.getQueryState(keys.spendBreakdown(7))?.isInvalidated).toBe(true)
        expect(client.getQueryState(keys.spendBreakdown(30))?.isInvalidated).toBe(true)
        expect(client.getQueryData(keys.spend)).toEqual(spend)

        client.setQueryData(keys.spendBreakdown(7), { days: 7 })
        applyStreamEvent(client, { type: 'tick.updated', tick: null, acknowledged: null })
        expect(client.getQueryState(keys.spendBreakdown(7))?.isInvalidated).toBe(true)
    })

    it('marks the spend breakdown stale when a run starts or ends, not when a cost moves', () => {
        const client = new QueryClient()
        const [first] = mockRuns
        if (!first) {
            throw new Error('fixtures are empty')
        }
        client.setQueryData(keys.runs, [first])
        client.setQueryData(keys.spendBreakdown(7), { days: 7 })
        applyStreamEvent(client, { type: 'runs.updated', runs: [{ ...first, cost_usd: (first.cost_usd ?? 0) + 1 }] })
        expect(client.getQueryState(keys.spendBreakdown(7))?.isInvalidated).toBe(false)
        applyStreamEvent(client, { type: 'runs.updated', runs: [{ ...first, state: 'failed' }] })
        expect(client.getQueryState(keys.spendBreakdown(7))?.isInvalidated).toBe(true)
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

    it('replaces the chores and marks every chore page stale, for a page to read again', () => {
        const client = new QueryClient()
        const detail = { chore: mockChores[0], runs: [], notes: [] } as unknown as ChoreDetail
        client.setQueryData(keys.chore('deps'), detail)

        applyStreamEvent(client, { type: 'chores.updated', chores: mockChores })

        expect(client.getQueryData(keys.chores)).toEqual(mockChores)
        expect(client.getQueryState(keys.chore('deps'))?.isInvalidated).toBe(true)
    })

    it("reads a chore run's page and transcript again only when its status moves", () => {
        const client = new QueryClient()
        const [chore] = mockChores
        const run = chore?.latest
        if (!chore || !run) {
            throw new Error('fixtures have no ended chore run')
        }
        const detail = { chore: chore.name, run, summary: null, note: null, findings: [] } as ChoreRunDetail
        client.setQueryData(keys.choreRun(chore.name, run.id), detail)
        client.setQueryData(keys.choreRunTranscript(chore.name, run.id), { status: 'read', entries: [] })

        applyStreamEvent(client, { type: 'chores.updated', chores: mockChores })
        expect(client.getQueryState(keys.choreRun(chore.name, run.id))?.isInvalidated).toBe(false)
        expect(client.getQueryState(keys.choreRunTranscript(chore.name, run.id))?.isInvalidated).toBe(false)

        client.setQueryData(keys.choreRun(chore.name, run.id), { ...detail, run: { ...run, status: 'running' } })
        applyStreamEvent(client, { type: 'chores.updated', chores: mockChores })
        expect(client.getQueryState(keys.choreRun(chore.name, run.id))?.isInvalidated).toBe(true)
        expect(client.getQueryState(keys.choreRunTranscript(chore.name, run.id))?.isInvalidated).toBe(true)
    })

    it('writes the pause whole, and lifts it', () => {
        const client = new QueryClient()
        const paused = { since: '2026-10-08T11:50:00Z', channel: 'loop' } as const

        applyStreamEvent(client, { type: 'loop.updated', paused, notice: null, memory: null })
        expect(client.getQueryData(keys.loop)).toEqual({ paused, notice: null, memory: null })
        const notice = {
            text: 'CI is down.',
            since: '2026-10-08T11:50:00Z',
            lapses_at: '2026-10-08T15:50:00Z',
            channel: 'web',
        } as const
        applyStreamEvent(client, { type: 'loop.updated', paused: null, notice, memory: null })
        expect(client.getQueryData(keys.loop)).toEqual({ paused: null, notice, memory: null })
    })

    it('marks the ticks and the tickets stale when the latest tick changes', () => {
        const client = new QueryClient()
        client.setQueryData(keys.ticks, [])
        client.setQueryData(keys.tickDetail(2), { tick: null, decisions: [], output_path: null })
        client.setQueryData(keys.ticket('ABC-102'), { ticket: mockTickets[0] })

        applyStreamEvent(client, { type: 'tick.updated', tick: null, acknowledged: 8 })

        expect(client.getQueryState(keys.ticks)?.isInvalidated).toBe(true)
        expect(client.getQueryState(keys.tickDetail(2))?.isInvalidated).toBe(true)
        expect(client.getQueryState(keys.ticket('ABC-102'))?.isInvalidated).toBe(true)
    })

    it('writes a run a page holds, and marks its transcript stale when its log has more in it', () => {
        const client = new QueryClient()
        const [first, second] = mockRuns
        if (!first || !second) {
            throw new Error('fixtures are empty')
        }
        const empty = { status: 'read', session_id: null, entries: [], truncated: false, unreadable: 0 } as const
        client.setQueryData(keys.run(first.id), first)
        client.setQueryData(keys.runTranscript(first.id), empty)
        client.setQueryData(keys.runTranscript(second.id), empty)

        // The same row again moves nothing.
        applyStreamEvent(client, { type: 'runs.updated', runs: mockRuns })
        expect(client.getQueryState(keys.runTranscript(first.id))?.isInvalidated).toBe(false)
        // A model call ended: the worker printed it, and its cost moved.
        applyStreamEvent(client, { type: 'runs.updated', runs: mockRuns.map((r) => ({ ...r, cost_usd: 9 })) })
        expect(client.getQueryData<Run>(keys.run(first.id))?.cost_usd).toBe(9)
        expect(client.getQueryState(keys.runTranscript(first.id))?.isInvalidated).toBe(true)
        // A run no page holds is not written into the cache.
        expect(client.getQueryData(keys.run(second.id))).toBeUndefined()

        // A tool call ended.
        client.setQueryData(keys.runTranscript(first.id), empty)
        const called = {
            ...first,
            cost_usd: 9,
            activity: { tool: 'bash', did: 'make check', at: '2026-10-08T12:29:00Z' },
        }
        applyStreamEvent(client, { type: 'runs.updated', runs: [called, ...mockRuns.slice(1)] })
        expect(client.getQueryState(keys.runTranscript(first.id))?.isInvalidated).toBe(true)
        client.setQueryData(keys.runTranscript(first.id), empty)

        const ended = { ...first, status: 'done', state: 'done', ended_at: '2026-10-08T12:20:00Z' } as const
        applyStreamEvent(client, { type: 'runs.updated', runs: [ended, ...mockRuns.slice(1)] })
        expect(client.getQueryData<Run>(keys.run(first.id))?.status).toBe('done')
        expect(client.getQueryState(keys.runTranscript(first.id))?.isInvalidated).toBe(true)
        expect(client.getQueryState(keys.runTranscript(second.id))?.isInvalidated).toBe(false)
    })

    it('marks a tick transcript stale when its status moves, not as it records decisions', () => {
        const client = new QueryClient()
        const empty = { status: 'read', session_id: null, entries: [], truncated: false, unreadable: 0 } as const
        const running = {
            id: 3,
            status: 'running',
            dry_run: false,
            started_at: '2026-10-08T12:00:00Z',
            ended_at: null,
            summary: null,
            session_id: null,
            cost_usd: null,
            new_tokens: null,
            peak_context: null,
            decisions: 0,
            idle: null,
            woken_by: null,
            canopy_version: null,
        }
        client.setQueryData(keys.tick, { tick: running, acknowledged: null })
        client.setQueryData(keys.tickTranscript(3), empty)
        client.setQueryData(keys.tickTranscript(2), empty)
        client.setQueryData(keys.tickOutput(3), { status: 'no_output', text: '', size: 0, truncated: false })

        applyStreamEvent(client, { type: 'tick.updated', tick: { ...running, decisions: 2 }, acknowledged: null })
        expect(client.getQueryState(keys.tickTranscript(3))?.isInvalidated).toBe(false)

        const ended = { ...running, status: 'ok', ended_at: '2026-10-08T12:01:00Z', decisions: 2 }
        applyStreamEvent(client, { type: 'tick.updated', tick: ended, acknowledged: null })
        expect(client.getQueryState(keys.tickTranscript(3))?.isInvalidated).toBe(true)
        // Its output with it: the overseer's file is written as the tick ends.
        expect(client.getQueryState(keys.tickOutput(3))?.isInvalidated).toBe(true)
        expect(client.getQueryState(keys.tickTranscript(2))?.isInvalidated).toBe(false)
    })

    it('marks the worktrees stale when a run starts or ends, not when its cost moves', () => {
        const client = new QueryClient()
        const [first] = mockRuns
        if (!first) {
            throw new Error('fixtures are empty')
        }
        client.setQueryData(keys.runs, mockRuns)
        client.setQueryData(keys.worktrees, [])

        applyStreamEvent(client, { type: 'runs.updated', runs: mockRuns.map((r) => ({ ...r, cost_usd: 9 })) })
        expect(client.getQueryState(keys.worktrees)?.isInvalidated).toBe(false)

        const ended = { ...first, status: 'done', state: 'done', ended_at: '2026-10-08T12:20:00Z' } as const
        applyStreamEvent(client, { type: 'runs.updated', runs: [ended, ...mockRuns.slice(1)] })
        expect(client.getQueryState(keys.worktrees)?.isInvalidated).toBe(true)
    })

    it('leaves the worktrees alone on the first runs a stream sends', () => {
        const client = new QueryClient()
        client.setQueryData(keys.worktrees, [])

        applyStreamEvent(client, { type: 'runs.updated', runs: mockRuns })

        expect(client.getQueryState(keys.worktrees)?.isInvalidated).toBe(false)
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
        const chores = { type: 'chores.updated', chores: mockChores }
        expect(parseStreamEvent(JSON.stringify(chores))).toEqual(chores)
        expect(parseStreamEvent('{"type":"chores.updated","chores":null}')).toBeNull()
        expect(parseStreamEvent('{"type":"ticket.changed","key":7}')).toBeNull()
        const day = { since: '2026-10-07T12:00:00Z', hours: 24, cost_usd: 2.5 }
        const spend = { type: 'spend.updated', spend: { day, month: { ...day, hours: 720 } } }
        expect(parseStreamEvent(JSON.stringify(spend))).toEqual(spend)
        expect(parseStreamEvent('{"type":"spend.updated","spend":null}')).toBeNull()
        const tick = '{"type":"tick.updated","tick":null,"acknowledged":7}'
        expect(parseStreamEvent(tick)).toEqual({ type: 'tick.updated', tick: null, acknowledged: 7 })
        expect(parseStreamEvent('{"type":"tick.updated"}')).toBeNull()
        expect(parseStreamEvent('{"type":"tick.updated","tick":null,"acknowledged":"7"}')).toBeNull()
        const paused = {
            type: 'loop.updated',
            paused: { since: '2026-10-08T11:50:00Z', channel: 'web' },
            notice: { text: 'CI is down.', since: '2026-10-08T11:50:00Z', lapses_at: '2026-10-08T15:50:00Z' },
            memory: null,
        }
        expect(parseStreamEvent(JSON.stringify(paused))).toEqual(paused)
        expect(parseStreamEvent('{"type":"loop.updated","paused":null,"notice":null,"memory":null}')).toEqual({
            type: 'loop.updated',
            paused: null,
            notice: null,
            memory: null,
        })
        expect(parseStreamEvent('{"type":"loop.updated","paused":null,"notice":null}')).toBeNull()
        expect(parseStreamEvent('{"type":"loop.updated","paused":null,"notice":null,"memory":"on"}')).toBeNull()
        expect(parseStreamEvent('{"type":"loop.updated"}')).toBeNull()
        expect(parseStreamEvent('{"type":"loop.updated","paused":null}')).toBeNull()
        expect(parseStreamEvent('{"type":"loop.updated","paused":null,"notice":"CI is down."}')).toBeNull()
        expect(parseStreamEvent('{"type":"loop.updated","paused":"yes"}')).toBeNull()
        expect(parseStreamEvent('null')).toBeNull()
    })
})
