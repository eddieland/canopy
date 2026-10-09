import { describe, expect, it } from 'vitest'

import { mockChores } from '@/api/mocks'

import { awaitsRun, choreLine, dueText, windowText } from './chores'

const [deps] = mockChores
if (!deps) throw new Error('fixtures are empty')
const NOW = Date.parse('2026-10-08T12:30:00Z')

describe('chores', () => {
    it('name the window a run may start in, as the CLI does', () => {
        expect(windowText(deps)).toBe('mon,tue,wed,thu,fri 08:00-18:00 UTC')
        expect(windowText({ days: [], hours: null, timezone: null })).toBe('any time')
        expect(windowText({ days: ['sat'], hours: null, timezone: null })).toBe('sat all day local time')
    })

    it('say when a chore is next due, now once that time has passed', () => {
        expect(dueText(deps, NOW)).toBe('due in 1h')
        expect(dueText(deps, Date.parse('2026-10-08T14:00:00Z'))).toBe('due now')
        expect(dueText({ due_at: null }, NOW)).toBe('due now')
    })

    it('put a chore on one line, as canopy status does', () => {
        expect(choreLine(deps, NOW)).toBe('last ok 4h ago, due in 1h')
        expect(choreLine({ ...deps, latest: null, due_at: null }, NOW)).toBe('never run, due now')
        const running = {
            ...deps.latest!,
            status: 'running',
            state: 'running' as const,
            started_at: '2026-10-08T12:20:00Z',
        }
        expect(choreLine({ ...deps, running }, NOW)).toBe('running for 10m')
    })

    it('mark a note no run has read: one after the latest run started', () => {
        expect(awaitsRun({ at: '2026-10-08T07:00:00Z' }, deps)).toBe(false)
        expect(awaitsRun({ at: '2026-10-08T12:00:00Z' }, deps)).toBe(true)
        const running = { ...deps.latest!, status: 'running', started_at: '2026-10-08T12:20:00Z' }
        expect(awaitsRun({ at: '2026-10-08T12:00:00Z' }, { ...deps, running })).toBe(false)
        expect(awaitsRun({ at: '2026-10-08T12:00:00Z' }, { running: null, latest: null })).toBe(true)
    })
})
