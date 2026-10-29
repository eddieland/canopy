import { describe, expect, it } from 'vitest'

import type { HostProcess } from '@/api/types'
import { busyTree, cpuText, processCount, processRows, processTree } from '@/lib/processes'

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
        expect(rows.map((r) => [r.node.process.pid, r.depth])).toEqual([
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

        expect(rows.map((r) => [r.node.process.pid, r.folded])).toEqual([
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
