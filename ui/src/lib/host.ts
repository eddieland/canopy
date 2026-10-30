// The machine the loop runs on (the system resources page, and the header's readout): how much of each resource it
// has left, and when that is worth the operator's look. The thresholds are here, not on the server: they say what the
// page colors, and the one the loop enforces, the tick's free-space floor, comes with each disk.

import type { Disk, DiskUse, HostResources } from '@/api/types'

/** How pressed a resource is: fine, worth a look, or past what canopy works with. */
export type Pressure = 'ok' | 'high' | 'critical'

/** A resource under pressure, as the header's readout and the page name it. */
export interface Concern {
    /** Which resource. */
    what: 'disk' | 'memory' | 'load'
    /** How pressed it is: never `ok`. */
    pressure: Exclude<Pressure, 'ok'>
    /** What is wrong, in a sentence: `412 MiB free where the workspace is, under the tick's floor of 2 GiB`. */
    text: string
}

/** Each pressure's text color: muted while fine, as what waits on the operator, as what is broken. */
export const PRESSURE_TEXT: Record<Pressure, string> = {
    ok: 'text-muted-foreground',
    high: 'text-status-blocked',
    critical: 'text-status-failed',
}

/** Each pressure as a counter's tone (`Counter`). */
export const PRESSURE_TONE = { ok: 'plain', high: 'blocked', critical: 'failed' } as const satisfies Record<
    Pressure,
    string
>

/** What canopy keeps on a disk, in a word or two each. */
export const DISK_USE: Record<DiskUse, string> = {
    workspace: 'the workspace',
    journal: 'the journal',
    temp: 'the temporary directory',
}

const KIB = 1024
const GIB = KIB ** 3
// Under this much free a build may fail partway, wherever it is: an agent's checkout and build take gigabytes.
const DISK_CRITICAL = GIB
// Under this much free, or twice the tick's floor, whichever is more, a few builds from full.
const DISK_HIGH = 10 * GIB
// The share of memory left under which a new agent or build is likely to swap, and under which it is soon refused.
const MEMORY_HIGH = 0.15
const MEMORY_CRITICAL = 0.05
// The change between the last minute's load and the last quarter hour's, as a share of the cores, past which the load
// is heading somewhere; never under half a process, so a machine of one or two cores does not flap on noise.
const LOAD_TREND_SHARE = 0.1
const LOAD_TREND_FLOOR = 0.5
const UNITS = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'] as const

/**
 * A size as a person reads it, in binary units as `df -h` counts: `412 GiB`, `9.8 GiB` (one decimal under ten),
 * `512 B`.
 */
export function bytesText(bytes: number): string {
    let value = bytes
    let unit = 0
    while (value >= KIB && unit < UNITS.length - 1) {
        value /= KIB
        unit += 1
    }
    const shown = unit > 0 && value < 10 ? value.toFixed(1) : Math.round(value).toString()
    return `${shown} ${UNITS[unit] ?? 'B'}`
}

/** The share of `total` in use when `free` is left, from 0 to 1; 0 for a size of nothing. */
export function usedShare(total: number, free: number): number {
    return total > 0 ? Math.min(1, Math.max(0, (total - free) / total)) : 0
}

/** A share as a whole percent: `63%`. */
export function percentText(share: number): string {
    return `${Math.round(share * 100)}%`
}

/** What canopy keeps on a disk, as a list in words: `the workspace and the journal`. */
export function diskHolds(disk: Disk): string {
    const words = disk.holds.map((use) => DISK_USE[use])
    return words.length < 2 ? (words[0] ?? '') : `${words.slice(0, -1).join(', ')} and ${words.at(-1) ?? ''}`
}

/**
 * How pressed a disk is: critical under the tick's floor, where a tick runs no overseer, or under a gigabyte anywhere;
 * high under ten gigabytes, or under twice the floor when that is more.
 */
export function diskPressure(disk: Disk): Pressure {
    const floor = disk.floor ?? 0
    if (disk.free < Math.max(floor, DISK_CRITICAL)) {
        return 'critical'
    }
    return disk.free < Math.max(2 * floor, DISK_HIGH) ? 'high' : 'ok'
}

/** How pressed memory is, by the share still available; fine when the operating system does not say. */
export function memoryPressure(memory: HostResources['memory']): Pressure {
    if (memory.total === null || memory.available === null || memory.total <= 0) {
        return 'ok'
    }
    const left = memory.available / memory.total
    return left < MEMORY_CRITICAL ? 'critical' : left < MEMORY_HIGH ? 'high' : 'ok'
}

/**
 * How pressed the processors are: high once the five minutes' load reaches the number of cores, where work waits for
 * a processor; never critical, since a busy machine still works, only slower.
 */
export function loadPressure(cpu: HostResources['cpu']): Pressure {
    const five = cpu.load?.[1]
    if (five === undefined || cpu.cores === null || cpu.cores <= 0) {
        return 'ok'
    }
    return five >= cpu.cores ? 'high' : 'ok'
}

/** Every resource under pressure, the worst first, then disks before memory before load. */
export function concerns(host: HostResources): Concern[] {
    const found: Concern[] = []
    for (const disk of host.disks) {
        const pressure = diskPressure(disk)
        if (pressure !== 'ok') {
            const under =
                disk.floor !== null && disk.free < disk.floor
                    ? `, under the tick's floor of ${bytesText(disk.floor)}: no tick runs the overseer`
                    : ''
            const verb = disk.holds.length > 1 ? 'are' : 'is'
            found.push({
                what: 'disk',
                pressure,
                text: `${bytesText(disk.free)} free where ${diskHolds(disk)} ${verb}${under}`,
            })
        }
    }
    const memory = memoryPressure(host.memory)
    if (memory !== 'ok') {
        found.push({
            what: 'memory',
            pressure: memory,
            text: `${bytesText(host.memory.available ?? 0)} of ${bytesText(host.memory.total ?? 0)} memory available`,
        })
    }
    if (loadPressure(host.cpu) !== 'ok') {
        const cores = host.cpu.cores ?? 0
        found.push({
            what: 'load',
            pressure: 'high',
            text:
                `load at ${percentText((host.cpu.load?.[1] ?? 0) / cores)} of ${cores} cores over five minutes: ` +
                'work waits for a processor',
        })
    }
    return found.toSorted((a, b) => Number(b.pressure === 'critical') - Number(a.pressure === 'critical'))
}

/** The worst of the host's pressures. */
export function hostPressure(host: HostResources): Pressure {
    return concerns(host)[0]?.pressure ?? 'ok'
}

/** The header's readout: `host ok`, or the worst concern in two words, `disk low`, `memory low`, or `host busy`. */
export function hostReadout(host: HostResources): string {
    const worst = concerns(host)[0]
    if (worst === undefined) {
        return 'host ok'
    }
    switch (worst.what) {
        case 'disk': {
            return 'disk low'
        }
        case 'memory': {
            return 'memory low'
        }
        case 'load': {
            return 'host busy'
        }
    }
}

/** A load average as `uptime` prints it, to two decimals: `1.87`. */
export function loadText(load: number): string {
    return load.toFixed(2)
}

/**
 * A load average as a share of the cores, the way to read it: 1 is every core busy, and past 1 work waits for a
 * processor. Null without the cores, where the number alone says nothing.
 */
export function coreShare(load: number, cores: number | null): number | null {
    return cores === null || cores <= 0 ? null : load / cores
}

/**
 * Which way the load is heading, the last minute's against the last quarter hour's: what the three averages `uptime`
 * prints are for. Null where the operating system keeps none.
 */
export function loadTrend(cpu: HostResources['cpu']): 'rising' | 'steady' | 'falling' | null {
    const [one, , fifteen] = cpu.load ?? []
    if (one === undefined || fifteen === undefined) {
        return null
    }
    const step = Math.max(LOAD_TREND_FLOOR, (cpu.cores ?? 0) * LOAD_TREND_SHARE)
    return one - fifteen >= step ? 'rising' : fifteen - one >= step ? 'falling' : 'steady'
}
