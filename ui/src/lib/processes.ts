// The machine's processes as the system resources page draws them: a tree, each parent over its children, the busiest
// first, with what a folded parent and its children add up to. Until the operator asks for every one, the tree is the
// loop's, each run's process under it, and what else is busy sits apart, so a machine of four hundred processes shows
// the dozen that answer "what is keeping it busy, and is it canopy?".

import type { HostProcess, ProcessState } from '@/api/types'

/** One process in the tree, with its children and what it and every process under it add up to. */
export interface ProcessNode {
    /** The process itself. */
    process: HostProcess
    /** Its children, the busiest first. */
    children: ProcessNode[]
    /** The processors it and every process under it kept busy: 1 is one core the whole time. */
    cpu: number
    /** The memory it and every process under it hold, in bytes. */
    rss: number
    /** How many processes are under it, at any depth, itself left out. */
    under: number
}

/** One line of the tree as the page draws it: a process, how deep it sits, and whether its children are folded. */
export interface ProcessRow {
    /** What the line is. */
    kind: 'process'
    /** The process and what it adds up to. */
    node: ProcessNode
    /** How many parents above it are drawn: 0 for a root. */
    depth: number
    /** Whether its children are hidden under it; false for one with none. */
    folded: boolean
}

/**
 * Parents that are only on the way to something, idle, each with one child shown, drawn as one muted line of their
 * names: `systemd › sshd › sshd › bash`. The line after it is the last one's child.
 */
export interface ChainRow {
    /** What the line is. */
    kind: 'chain'
    /** The parents, outermost first. */
    nodes: ProcessNode[]
    /** How many parents above the first are drawn. */
    depth: number
}

/** A line of the tree. */
export type TreeLine = ProcessRow | ChainRow

/** How each list of siblings is ordered: the busiest first, or the one holding the most memory. */
export type ProcessOrder = 'cpu' | 'memory'

/** A part of the tree the page draws under a heading of its own, or none. */
export interface ProcessSection {
    /** Its heading, `elsewhere`; null for the loop's, and for every process at once. */
    heading: string | null
    /** The loop's parents, outermost first, which the page names in one muted line over it; empty for the rest. */
    above: HostProcess[]
    /** Its trees. */
    roots: ProcessNode[]
}

/** What the page draws of the processes: its sections, and how many processes it leaves out as idle. */
export interface ProcessView {
    /** The loop's tree, then what else is busy; or every process, in one. */
    sections: ProcessSection[]
    /** How many processes no section shows. */
    hidden: number
}

/** A process as busy as this, or any under it, is kept when the tree is pruned: 1% of a core. */
export const BUSY_CPU = 0.01

/** The states the load average counts, which keep a process in a pruned tree however little it used. */
const LOADED: ReadonlySet<ProcessState> = new Set(['running', 'disk'])

/** What each state reads as beside a process's name; a sleeping or idle one, nearly every one, says nothing. */
export const STATE_TEXT: Partial<Record<ProcessState, string>> = {
    running: 'running',
    disk: 'waiting on a disk',
    stopped: 'stopped',
    zombie: 'zombie',
}

/**
 * The tree of `processes`: each under its parent, a process whose parent is not listed a root, and each list of
 * siblings the busiest first, then the one holding the most memory, then the oldest pid.
 */
export function processTree(processes: readonly HostProcess[]): ProcessNode[] {
    const nodes = new Map<number, ProcessNode>()
    for (const process of processes) {
        nodes.set(process.pid, { process, children: [], cpu: process.cpu, rss: process.rss, under: 0 })
    }
    const roots: ProcessNode[] = []
    for (const node of nodes.values()) {
        const parent = nodes.get(node.process.parent)
        // A parent that is the process itself would make a loop; Linux never says so, but the page must not hang.
        if (parent === undefined || parent === node) {
            roots.push(node)
        } else {
            parent.children.push(node)
        }
    }
    for (const root of roots) {
        total(root)
    }
    return roots.toSorted(busiest)
}

/**
 * `roots` with only what is worth a look: a process kept busy by it or anything under it (`BUSY_CPU`), one the load
 * counts, and the ones `keep` names, each with the parents above it so it is seen where it runs. What each adds up to
 * is still all of what is under it.
 */
export function busyTree(roots: readonly ProcessNode[], keep: ReadonlySet<number> = new Set()): ProcessNode[] {
    return roots.flatMap((root) => {
        const pruned = prune(root, keep)
        return pruned === null ? [] : [pruned]
    })
}

/**
 * What the page draws of `processes`. With `all`, every one in one tree. Otherwise the loop's tree, rooted at its
 * process `loop` with its parents named over it, keeping each run's process however idle (one the journal ties to its
 * work) and whatever under them is busy; then, `elsewhere`, whatever else is busy, with its parents but the loop's idle
 * ones, which the line over the loop already names. Each tree adds up only what is in it, so `elsewhere` does not count
 * the loop's work again. Where the loop is not among them, the busy ones in one tree.
 */
export function processView(processes: readonly HostProcess[], loop: number, all: boolean): ProcessView {
    const whole = processTree(processes)
    if (all) {
        return { sections: [{ heading: null, above: [], roots: whole }], hidden: 0 }
    }
    const keep = new Set([loop, ...processes.filter((p) => p.work !== null).map((p) => p.pid)])
    const root = find(whole, loop)
    if (root === undefined) {
        const pruned = busyTree(whole, keep)
        return {
            sections: [{ heading: null, above: [], roots: pruned }],
            hidden: processCount(whole) - processCount(pruned),
        }
    }
    const ours = busyTree([root], keep)
    const above = parentsOf(processes, loop)
    const named = new Set([...pidsOf([root]), ...above.filter((p) => !busy(p)).map((p) => p.pid)])
    const elsewhere = busyTree(processTree(processes.filter((p) => !named.has(p.pid))), keep)
    const sections: ProcessSection[] = [{ heading: null, above, roots: ours }]
    if (elsewhere.length > 0) {
        sections.push({ heading: 'elsewhere', above: [], roots: elsewhere })
    }
    const shown = new Set([...pidsOf(ours), ...above.map((p) => p.pid), ...pidsOf(elsewhere)])
    return { sections, hidden: processes.length - shown.size }
}

/** How many processes `roots` hold, at any depth: in a pruned tree, the ones it kept, whatever each adds up to. */
export function processCount(roots: readonly ProcessNode[]): number {
    return roots.reduce((n, root) => n + 1 + processCount(root.children), 0)
}

/**
 * The lines of `roots` the page draws, parents first, leaving out the children of each process `folded` names, each
 * list of siblings in `order`. With `chain`, a run of two or more idle parents on the way to one child each is drawn
 * as one line (`ChainRow`), but for the processes `chain` names, which always have a line of their own.
 */
export function processRows(
    roots: readonly ProcessNode[],
    folded: ReadonlySet<number>,
    { order = 'cpu', chain }: { order?: ProcessOrder; chain?: ReadonlySet<number> } = {},
): TreeLine[] {
    const rows: TreeLine[] = []
    const passing = (node: ProcessNode) =>
        chain !== undefined &&
        !chain.has(node.process.pid) &&
        node.process.work === null &&
        !busy(node.process) &&
        node.children.length === 1 &&
        !folded.has(node.process.pid)
    const walk = (nodes: readonly ProcessNode[], depth: number) => {
        for (const first of order === 'cpu' ? nodes : nodes.toSorted(heaviest)) {
            const run: ProcessNode[] = []
            let node = first
            for (let next = node.children[0]; passing(node) && next !== undefined; next = node.children[0]) {
                run.push(node)
                node = next
            }
            if (run.length < 2) {
                node = first
            } else {
                rows.push({ kind: 'chain', nodes: run, depth })
            }
            const at = run.length < 2 ? depth : depth + 1
            const closed = node.children.length > 0 && folded.has(node.process.pid)
            rows.push({ kind: 'process', node, depth: at, folded: closed })
            if (!closed) {
                walk(node.children, at + 1)
            }
        }
    }
    walk(roots, 0)
    return rows
}

/**
 * The processors a process kept busy, as a share of one core as `top` shows it: `196%` for two cores nearly all the
 * time, one decimal under ten, `0.4%`.
 */
export function cpuText(cpu: number): string {
    const percent = cpu * 100
    return percent < 10 ? `${percent.toFixed(1)}%` : `${Math.round(percent)}%`
}

// Fill in what `node` and everything under it add up to, and order each list of siblings, from the leaves up. A stack,
// not recursion: a chain of a few thousand shells is unlikely, but the page must not overflow on one.
function total(root: ProcessNode) {
    const order: ProcessNode[] = []
    const stack = [root]
    for (let node = stack.pop(); node !== undefined; node = stack.pop()) {
        order.push(node)
        stack.push(...node.children)
    }
    for (const node of order.toReversed()) {
        node.children.sort(busiest)
        for (const child of node.children) {
            node.cpu += child.cpu
            node.rss += child.rss
            node.under += 1 + child.under
        }
    }
}

// The busier first, then the one holding more memory, then the lower pid, the older as a rule.
function busiest(a: ProcessNode, b: ProcessNode): number {
    if (a.cpu !== b.cpu) {
        return b.cpu - a.cpu
    }
    return a.rss === b.rss ? a.process.pid - b.process.pid : b.rss - a.rss
}

// Whether `process` itself is worth a look: busy, or one the load counts.
function busy(process: HostProcess): boolean {
    return process.cpu >= BUSY_CPU || LOADED.has(process.state)
}

// The holding more memory first, then the busier, then the lower pid.
function heaviest(a: ProcessNode, b: ProcessNode): number {
    if (a.rss !== b.rss) {
        return b.rss - a.rss
    }
    return a.cpu === b.cpu ? a.process.pid - b.process.pid : b.cpu - a.cpu
}

// The node of process `pid` in `roots`, at any depth.
function find(roots: readonly ProcessNode[], pid: number): ProcessNode | undefined {
    const stack = [...roots]
    for (let node = stack.pop(); node !== undefined; node = stack.pop()) {
        if (node.process.pid === pid) {
            return node
        }
        stack.push(...node.children)
    }
    return undefined
}

// Every pid in `roots`, at any depth.
function pidsOf(roots: readonly ProcessNode[]): number[] {
    const found: number[] = []
    const stack = [...roots]
    for (let node = stack.pop(); node !== undefined; node = stack.pop()) {
        found.push(node.process.pid)
        stack.push(...node.children)
    }
    return found
}

// The parents of process `pid`, outermost first; a parent listed twice ends the walk, so a loop in them cannot hang it.
function parentsOf(processes: readonly HostProcess[], pid: number): HostProcess[] {
    const by = new Map(processes.map((p) => [p.pid, p]))
    const found: HostProcess[] = []
    const seen = new Set([pid])
    for (let p = by.get(by.get(pid)?.parent ?? -1); p !== undefined && !seen.has(p.pid); p = by.get(p.parent)) {
        seen.add(p.pid)
        found.push(p)
    }
    return found.toReversed()
}

// `node` with only its children worth a look, or null when neither it nor anything under it is.
function prune(node: ProcessNode, keep: ReadonlySet<number>): ProcessNode | null {
    const children = busyTree(node.children, keep)
    const own = node.cpu >= BUSY_CPU || LOADED.has(node.process.state) || keep.has(node.process.pid)
    return own || children.length > 0 ? { ...node, children } : null
}
