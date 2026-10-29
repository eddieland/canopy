// The machine's processes as the system resources page draws them: a tree, each parent over its children, the busiest
// first, with what a folded parent and its children add up to. Pruned to the busy ones until the operator asks for
// every one, so a machine of four hundred processes shows the dozen that answer "what is keeping it busy?".

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
    /** The process and what it adds up to. */
    node: ProcessNode
    /** How many parents above it are drawn: 0 for a root. */
    depth: number
    /** Whether its children are hidden under it; false for one with none. */
    folded: boolean
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

/** How many processes `roots` hold, at any depth: in a pruned tree, the ones it kept, whatever each adds up to. */
export function processCount(roots: readonly ProcessNode[]): number {
    return roots.reduce((n, root) => n + 1 + processCount(root.children), 0)
}

/** The lines of `roots` the page draws, parents first, leaving out the children of each process `folded` names. */
export function processRows(roots: readonly ProcessNode[], folded: ReadonlySet<number>): ProcessRow[] {
    const rows: ProcessRow[] = []
    const walk = (nodes: readonly ProcessNode[], depth: number) => {
        for (const node of nodes) {
            const closed = node.children.length > 0 && folded.has(node.process.pid)
            rows.push({ node, depth, folded: closed })
            if (!closed) {
                walk(node.children, depth + 1)
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

// `node` with only its children worth a look, or null when neither it nor anything under it is.
function prune(node: ProcessNode, keep: ReadonlySet<number>): ProcessNode | null {
    const children = busyTree(node.children, keep)
    const own = node.cpu >= BUSY_CPU || LOADED.has(node.process.state) || keep.has(node.process.pid)
    return own || children.length > 0 ? { ...node, children } : null
}
