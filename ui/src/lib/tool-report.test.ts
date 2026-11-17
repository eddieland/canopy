import { describe, expect, it } from 'vitest'

import type { ToolsAgent, ToolsRow, ToolsUse } from '@/api/types'

import {
    callRate,
    failedTip,
    kindText,
    kindTip,
    offersText,
    pickedAgent,
    rateText,
    rateTip,
    rowKey,
    sortedAgents,
    sortedRows,
    toolRows,
    toolsAgent,
    toolsFigures,
    toolsLine,
    toolsSort,
    toolsWindow,
} from './tool-report'

function used(by: string, counts: Partial<ToolsUse> = {}): ToolsUse {
    return {
        agent: by,
        offered: 4,
        partial: 0,
        called: 0,
        unoffered: 0,
        calls: 0,
        errors: 0,
        est_result_tokens: 0,
        ...counts,
    }
}

function row(name: string, counts: Partial<ToolsRow> = {}): ToolsRow {
    return {
        kind: 'tool',
        name,
        server: null,
        listed: true,
        unused: false,
        offered: 9,
        partial: 0,
        called: 6,
        unoffered: 0,
        calls: 40,
        errors: 2,
        est_result_tokens: 9_000,
        uses: [],
        ...counts,
    }
}

function agent(name: string, counts: Partial<ToolsAgent> = {}): ToolsAgent {
    return {
        agent: name,
        runs: 4,
        unanswered: 0,
        unasked: 0,
        servers: 2,
        tools: 7,
        unused: 3,
        calls: 100,
        errors: 4,
        est_result_tokens: 20_000,
        ...counts,
    }
}

const GITHUB = row('github', { kind: 'server', offered: 9, partial: 5, called: 2, calls: 12, errors: 0 })
const SENTRY = row('sentry', { kind: 'server', unused: true, offered: 6, called: 0, calls: 0, errors: 0 })
const READ = row('github_pull_request_read', { server: 'github', listed: false, offered: 0, called: 0, unoffered: 2 })
const STRAY = row('elsewhere_tool', { listed: false, offered: 0, called: 0, unoffered: 1, calls: 1, errors: 1 })
const GLOB = row('glob', { unused: true, called: 0, calls: 0, errors: 0, est_result_tokens: 0 })
const SHELL = row('shell', { called: 9, unoffered: 3, calls: 149, errors: 13, est_result_tokens: 81_000 })

describe('the search params', () => {
    it('keep a window, an order, and an agent the page offers, and drop the defaults', () => {
        expect(toolsWindow({ days: 30 })).toEqual({ days: 30 })
        expect(toolsWindow({ days: 7 })).toEqual({ days: 7 })
        expect(toolsWindow({ days: 3 })).toBeUndefined()
        expect(toolsSort({ order: 'failed' })).toBe('failed')
        expect(toolsSort({ order: 'most' })).toBeUndefined()
        expect(toolsSort({ order: 'cost' })).toBeUndefined()
        expect(toolsAgent({ agent: 'canopy-worker' })).toBe('canopy-worker')
        expect(toolsAgent({ agent: '' })).toBeUndefined()
        expect(toolsAgent({ agent: 3 })).toBeUndefined()
    })

    it('hold a picked agent to the agents the window has', () => {
        const agents = [agent('canopy-worker')]
        expect(pickedAgent(agents, 'canopy-worker')).toBe(agents[0])
        expect(pickedAgent(agents, 'nobody')).toBeUndefined()
        expect(pickedAgent(agents, undefined)).toBeUndefined()
    })
})

describe('the rows', () => {
    it("are every agent's, or the picked agent's own, unused by its own runs alone", () => {
        const shell = row('shell', {
            uses: [used('canopy-worker', { called: 4, calls: 30 }), used('canopy-reviewer', { offered: 5 })],
        })
        const glob = row('glob', { uses: [used('canopy-worker')] })
        expect(toolRows([shell, glob], undefined)).toEqual([shell, glob])
        const own = toolRows([shell, glob], 'canopy-reviewer')
        expect(own.map((r) => [r.name, r.offered, r.calls, r.unused])).toEqual([['shell', 5, 0, true]])
        expect(toolRows([shell, glob], 'nobody')).toEqual([])
    })

    it('tell a server from a tool of its name', () => {
        expect(rowKey({ kind: 'server', name: 'read' })).not.toBe(rowKey({ kind: 'tool', name: 'read' }))
    })

    it('sort by the most calls, the least called, what came back, or what failed', () => {
        const rows = [GITHUB, SENTRY, READ, STRAY, GLOB, SHELL]
        const names = (sort?: Parameters<typeof sortedRows>[1]) => sortedRows(rows, sort).map((r) => r.name)
        expect(names()).toEqual(['shell', 'github_pull_request_read', 'github', 'elsewhere_tool', 'glob', 'sentry'])
        // Never called first, the most runs offered first among them; a row no offer names has no rate, and is last.
        expect(names('least')).toEqual([
            'glob',
            'sentry',
            'github',
            'shell',
            'elsewhere_tool',
            'github_pull_request_read',
        ])
        expect(names('returned')[0]).toBe('shell')
        expect(names('failed').slice(0, 3)).toEqual(['shell', 'github_pull_request_read', 'elsewhere_tool'])
    })
})

describe('a call rate', () => {
    it('is the runs that called it of the runs offered it, never for none, a dash with no offer', () => {
        expect(callRate(SHELL)).toBe(1)
        expect(rateText(SHELL)).toBe('100%')
        expect(rateText(GITHUB)).toBe('22%')
        expect(rateText(GLOB)).toBe('never')
        expect(rateText(READ)).toBe('–')
        expect(rateText(row('rare', { offered: 400, called: 1 }))).toBe('<1%')
        // Called only by runs with no offer on record: not never, since it was called.
        expect(rateText(row('odd', { offered: 2, called: 0, unoffered: 1, calls: 3 }))).toBe('0%')
    })

    it('says what it counts on its tip, or why there is none', () => {
        expect(rateTip(GITHUB)).toBe('called in 2 of the 9 runs offered it · 5 of them offered only some of its tools')
        expect(rateTip(SHELL)).toBe('called in 9 of the 9 runs offered it · called in 3 runs with no offer on record')
        expect(rateTip(READ)).toBe('an offer names github, not its tools: known by its calls, in 2 runs')
        expect(rateTip(STRAY)).toBe('no offer on record names it, or a server it is of')
    })
})

describe('a kind', () => {
    it('says what a row is, and where a tool no offer names comes from', () => {
        expect([GITHUB, SHELL, READ, STRAY].map((r) => kindText(r))).toEqual([
            'MCP server',
            'built in',
            'of github',
            'tool',
        ])
        expect(kindTip(GITHUB)).toBe("its figures are its tools' together")
        expect(kindTip(READ)).toBe("its name opens with github's, as the runtime names a server's tools")
    })
})

describe('the headline', () => {
    it('counts what was offered, what was never called, and the calls', () => {
        const found = { days: 7, servers: 3, tools: 7, unused: 4, calls: 292, errors: 15 }
        expect(toolsLine(found)).toBe(
            '3 servers and 7 tools offered over 7 days · 4 never called · 292 calls, 15 failed',
        )
        expect(toolsLine({ ...found, servers: 1, unused: 0, errors: 0 })).toBe(
            '1 server and 7 tools offered over 7 days · each one called · 292 calls',
        )
        expect(toolsLine({ ...found, servers: 0, tools: 0, unused: 0, calls: 2, errors: 0 })).toBe(
            'no server or tool offered over 7 days · 2 calls',
        )
        expect(toolsLine({ ...found, servers: 0, tools: 0, unused: 0, calls: 0, errors: 0 })).toBe(
            'no server or tool offered over 7 days',
        )
        expect(toolsFigures(found)).toEqual({ offered: 10, unused: 4, calls: 292, errors: 15 })
    })
})

describe('the agents', () => {
    it('are listed by their calls, then their runs', () => {
        const agents = [
            agent('quiet', { calls: 0, runs: 2 }),
            agent('busy', { calls: 160 }),
            agent('idle', { calls: 0, runs: 8 }),
        ]
        expect(sortedAgents(agents).map((a) => a.agent)).toEqual(['busy', 'idle', 'quiet'])
    })

    it('say what share of their calls failed', () => {
        expect(failedTip({ calls: 160, errors: 12 })).toBe('8% of 160 calls')
        expect(failedTip({ calls: 0, errors: 0 })).toBeUndefined()
    })

    it('say how many runs have no offer on record, and why', () => {
        expect(offersText({ runs: 0, unanswered: 0, unasked: 0 })).toBe('')
        expect(offersText({ runs: 1, unanswered: 0, unasked: 0 })).toBe('Each of the 1 run has its offer on record.')
        expect(offersText({ runs: 30, unanswered: 1, unasked: 8 })).toBe(
            'No offer on record for 9 of 30 runs: the runtime could not answer for 1, and canopy never asked about ' +
                "8, a task's, an epic's plan, or one from before it asked. They count under the agent canopy ships " +
                'for their kind of run, and their calls are counted.',
        )
    })
})
