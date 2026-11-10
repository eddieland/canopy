import { describe, expect, it } from 'vitest'

import type { HostProcess } from '@/api/types'
import { busyTree, cpuText, processCount, processRows, processTree, processView } from '@/lib/processes'
import type { TreeLine } from '@/lib/processes'

function process(pid: number, parent: number, cpu = 0, fields: Partial<HostProcess> = {}): HostProcess {
    return {
        pid,
        parent,
        name: `p${pid}`,
        command: `p${pid}`,
        user: 'operator',
        state: 'sleeping',
        cpu,
        rss: 1024,
        threads: 1,
        started_at: null,
        work: null,
        ...fields,
    }
}

// init, with a shell under it running a build of two compilers, and an idle editor.
const MACHINE = [
    process(1, 0, 0.001),
    process(10, 1),
    process(11, 10, 0.05),
    process(12, 11, 0.9, { state: 'running' }),
    process(13, 11, 1.1, { state: 'running' }),
    process(20, 1, 0.002),
]

// Each process line's pid and depth, and each chain's pids, as `chain 1 10`.
function lines(rows: readonly TreeLine[]): (string | [number, number])[] {
    return rows.map((r) =>
        r.kind === 'chain' ? `chain ${r.nodes.map((n) => n.process.pid).join(' ')}` : [r.node.process.pid, r.depth],
    )
}

function pids(nodes: readonly { process: HostProcess; children: readonly unknown[] }[]): number[] {
    return nodes.map((n) => n.process.pid)
}

describe('processTree', () => {
    it('puts each process under its parent, the busiest first, adding up what each holds', () => {
        const [init] = processTree(MACHINE)

        expect(init?.process.pid).toBe(1)
        expect(pids(init?.children ?? [])).toEqual([10, 20])
        const build = init?.children[0]?.children[0]
        expect(pids(build?.children ?? [])).toEqual([13, 12])
        expect(build?.cpu).toBeCloseTo(2.05)
        expect(init?.cpu).toBeCloseTo(2.053)
        expect(init?.rss).toBe(6 * 1024)
        expect(init?.under).toBe(5)
    })

    it('makes a root of a process whose parent is not listed, or is itself', () => {
        const roots = processTree([process(5, 99), process(6, 6), process(7, 5, 0.5)])

        expect(pids(roots)).toEqual([5, 6])
        expect(processCount(roots)).toBe(3)
    })
})

describe('busyTree', () => {
    it('keeps the busy processes and their parents, and drops the idle ones', () => {
        const busy = busyTree(processTree(MACHINE))

        const rows = processRows(busy, new Set())
        expect(lines(rows)).toEqual([
            [1, 0],
            [10, 1],
            [11, 2],
            [13, 3],
            [12, 3],
        ])
        // What a parent adds up to is still all of what is under it, though only the busy ones are counted shown.
        expect(busy[0]?.under).toBe(5)
        expect(processCount(busy)).toBe(5)
    })

    it('keeps a process the load counts however little it used, and one asked for', () => {
        const busy = busyTree(
            processTree([process(1, 0), process(2, 1, 0, { state: 'disk' }), process(3, 1)]),
            new Set([3]),
        )

        expect(pids(busy[0]?.children ?? [])).toEqual([2, 3])
    })

    it('keeps nothing of a machine at rest', () => {
        expect(busyTree(processTree([process(1, 0), process(2, 1)]))).toEqual([])
    })
})

describe('processRows', () => {
    it("leaves out a folded process's children, and says it is folded", () => {
        const rows = processRows(processTree(MACHINE), new Set([10, 12]))

        expect(rows.map((r) => (r.kind === 'process' ? [r.node.process.pid, r.folded] : r.kind))).toEqual([
            [1, false],
            [10, true],
            [20, false],
        ])
    })
})

describe('cpuText', () => {
    it('reads as a share of one core, one decimal under ten', () => {
        expect(cpuText(0)).toBe('0.0%')
        expect(cpuText(0.004)).toBe('0.4%')
        expect(cpuText(0.982)).toBe('98%')
        expect(cpuText(1.96)).toBe('196%')
    })
})

// A login's chain down to a shell, the loop under it with two runs, one compiling, an idle helper of the loop's, and an
// editor's server busy beside the loop under the same shell.
const LOGIN = [
    process(1, 0),
    process(2, 1),
    process(3, 2),
    process(4, 3),
    process(50, 4, 0.03),
    process(60, 50, 0, {
        work: { kind: 'run', id: 41, ticket_key: 'ABC-1', pr_url: null, chore: null, task_id: null, epic_id: null },
    }),
    process(61, 60, 0.1),
    process(62, 61, 0.95, { state: 'running', rss: 900 }),
    process(70, 50, 0, {
        work: { kind: 'chore', id: 4, ticket_key: null, pr_url: null, chore: 'deps', task_id: null, epic_id: null },
    }),
    process(71, 50),
    process(80, 4, 0.02),
]

describe('processView', () => {
    it("roots the tree at the loop, names its parents over it, and keeps each run's process however idle", () => {
        const view = processView(LOGIN, 50, false)
        const [ours, elsewhere] = view.sections

        expect(ours?.heading).toBeNull()
        expect(ours?.above.map((p) => p.pid)).toEqual([1, 2, 3, 4])
        expect(lines(processRows(ours?.roots ?? [], new Set()))).toEqual([
            [50, 0],
            [60, 1],
            [61, 2],
            [62, 3],
            [70, 1],
        ])
        // What a run adds up to is what is under it, the compiler's included.
        expect(ours?.roots[0]?.children[0]?.cpu).toBeCloseTo(1.05)
        expect(elsewhere?.heading).toBe('elsewhere')
        // The idle helper is all that is left out: the parents are named over the loop.
        expect(view.hidden).toBe(1)
    })

    it("puts what else is busy under elsewhere, adding up only what is there, the loop's idle parents left out", () => {
        const [, elsewhere] = processView(LOGIN, 50, false).sections

        // The editor's server's parents are the loop's, named over the loop already.
        expect(lines(processRows(elsewhere?.roots ?? [], new Set(), { chain: new Set([50]) }))).toEqual([[80, 0]])
        expect(elsewhere?.roots[0]?.cpu).toBeCloseTo(0.02)
    })

    it("keeps a parent of the loop's in elsewhere while it is busy itself", () => {
        const busyShell = LOGIN.map((p) => (p.pid === 4 ? { ...p, cpu: 0.2 } : p))
        const [, elsewhere] = processView(busyShell, 50, false).sections

        expect(lines(processRows(elsewhere?.roots ?? [], new Set()))).toEqual([
            [4, 0],
            [80, 1],
        ])
    })

    it('shows every process in one tree on asking, and the busy ones where the loop is not among them', () => {
        expect(processView(LOGIN, 50, true)).toEqual({
            sections: [{ heading: null, above: [], roots: processTree(LOGIN) }],
            hidden: 0,
        })
        const lost = processView(LOGIN, 999, false)
        expect(lost.sections).toHaveLength(1)
        expect(lost.sections[0]?.heading).toBeNull()
    })
})

describe('processRows with chains and an order', () => {
    it('never chains a single idle parent, a run, or one named, and keeps a folded one whole', () => {
        const roots = processTree(LOGIN)

        expect(lines(processRows(roots, new Set([2]), { chain: new Set() }))[0]).toEqual([1, 0])
        const kept = lines(processRows(roots, new Set(), { chain: new Set([50]) }))
        // The shell has two children, the loop and the editor's server, so the chain stops over it.
        expect(kept.slice(0, 3)).toEqual(['chain 1 2 3', [4, 1], [50, 2]])
        expect(kept).toContainEqual([60, 3])
    })

    it('orders siblings by the memory they hold when asked', () => {
        const roots = processTree([process(1, 0), process(2, 1, 0.5, { rss: 10 }), process(3, 1, 0.1, { rss: 99 })])

        expect(lines(processRows(roots, new Set())).slice(1)).toEqual([
            [2, 1],
            [3, 1],
        ])
        expect(lines(processRows(roots, new Set(), { order: 'memory' })).slice(1)).toEqual([
            [3, 1],
            [2, 1],
        ])
    })
})
