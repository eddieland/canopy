import { describe, expect, it } from 'vitest'

import { mockChores } from '@/api/mocks'

import {
    awaitsRun,
    cadenceText,
    choreHealth,
    choreLine,
    choreRunState,
    dueText,
    findingsReadout,
    findingsText,
    listedText,
    overLimitText,
    runsText,
    startsAnyTime,
    windowText,
} from './chores'

const [deps] = mockChores
if (!deps?.latest) {
    throw new Error('fixtures are empty')
}
const { latest } = deps
const NOW = Date.parse('2026-10-08T12:30:00Z')

describe('chores', () => {
    it('name the window a run may start in, as the CLI does', () => {
        expect(windowText(deps)).toBe('mon,tue,wed,thu,fri 08:00-18:00 UTC')
        expect(windowText({ days: [], hours: null, timezone: null })).toBe('any time')
        expect(windowText({ days: ['sat'], hours: null, timezone: null })).toBe('sat all day local time')
        expect(startsAnyTime(deps)).toBe(false)
        expect(startsAnyTime({ days: [], hours: null })).toBe(true)
        expect(startsAnyTime({ days: [], hours: '08:00-18:00' })).toBe(false)
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
            ...latest,
            status: 'running',
            state: 'running' as const,
            started_at: '2026-10-08T12:20:00Z',
        }
        expect(choreLine({ ...deps, running }, NOW)).toBe('running for 10m')
    })

    it("say on a chore's page how healthy it is: where it stands, how its last run ended, its open findings", () => {
        expect(choreHealth(deps, NOW)).toBe('last ok 4h ago, due in 1h · 1 open finding')
        const running = {
            ...latest,
            status: 'running',
            state: 'running' as const,
            started_at: '2026-10-08T12:20:00Z',
        }
        expect(choreHealth({ ...deps, running }, NOW)).toBe('running for 10m · last ok 4h ago · 1 open finding')
        expect(choreHealth({ ...deps, running, latest: null, findings: [] }, NOW)).toBe('running for 10m')
        expect(choreHealth({ ...deps, findings: [] }, NOW)).toBe('last ok 4h ago, due in 1h')
        expect(choreHealth({ ...deps, findings: deps.findings.map((f) => ({ ...f, dismissed: true })) }, NOW)).toBe(
            'last ok 4h ago, due in 1h',
        )
        expect(choreHealth({ ...deps, findings: [], more_findings: 12 }, NOW)).toBe(
            'last ok 4h ago, due in 1h · 0 open findings · 12 not listed',
        )
    })

    it("count a window's runs, and the ones that reported no cost", () => {
        expect(runsText(deps.spend.day)).toBe('2')
        expect(runsText(deps.spend.month)).toBe('4, 1 unpriced')
        expect(runsText({ runs: 0, priced: 0 })).toBe('0')
    })

    it('count the findings still waiting as open, and the dismissed ones apart, as canopy status does', () => {
        expect(findingsText(deps.findings)).toBe('1 open finding')
        expect(findingsText([])).toBe('0 open findings')
        const waiting = { dismissed: false }
        const dismissed = { dismissed: true }
        expect(findingsText([waiting, dismissed, waiting])).toBe('2 open findings · 1 dismissed')
        expect(findingsText([dismissed, dismissed])).toBe('0 open findings · 2 dismissed')
        expect(findingsReadout(deps.findings)).toBe('1')
        expect(findingsReadout([dismissed, waiting, dismissed])).toBe('1 · 2 dismissed')
    })

    it('count the findings a run found past its max_findings as not listed', () => {
        const waiting = { dismissed: false }
        const dismissed = { dismissed: true }
        expect(findingsText([waiting, dismissed], 12)).toBe('1 open finding · 1 dismissed · 12 not listed')
        expect(findingsReadout([waiting], 3)).toBe('1 · 3 not listed')
        expect(listedText(5, 7)).toBe('5 findings · 7 not listed')
        expect(listedText(1, 0)).toBe('1 finding')
        expect(overLimitText(5, 12)).toBe('its latest ok run found 12 more than the 5 it may list.')
    })

    it('mark a note no run has read: one after the latest run started', () => {
        expect(awaitsRun({ at: '2026-10-08T07:00:00Z' }, deps)).toBe(false)
        expect(awaitsRun({ at: '2026-10-08T12:00:00Z' }, deps)).toBe(true)
        const running = { ...latest, status: 'running', started_at: '2026-10-08T12:20:00Z' }
        expect(awaitsRun({ at: '2026-10-08T12:00:00Z' }, { ...deps, running })).toBe(false)
        expect(awaitsRun({ at: '2026-10-08T12:00:00Z' }, { running: null, latest: null })).toBe(true)
    })
})

describe('cadenceText', () => {
    it('says how often a chore may start in minutes, as the config and the CLI do', () => {
        expect(cadenceText(360)).toBe('every 360 minutes')
        expect(cadenceText(1)).toBe('every minute')
    })
})

describe('choreRunState', () => {
    it('groups a chore run by its status as the server does', () => {
        expect(choreRunState('running')).toBe('running')
        expect(choreRunState('ok')).toBe('done')
        expect(choreRunState('crashed')).toBe('failed')
        expect(choreRunState('failed')).toBe('failed')
    })
})
