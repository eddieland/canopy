import { describe, expect, it } from 'vitest'

import { mockHost } from '@/api/mocks'
import type { Disk } from '@/api/types'
import type { Trend } from '@/lib/trend'

import {
    bytesText,
    concerns,
    coreShare,
    diskHolds,
    diskPressure,
    fillsIn,
    fillsInText,
    hostPressure,
    hostReadout,
    loadTrend,
    memoryPressure,
} from './host'

const GIB = 1024 ** 3
const MIB = 1024 ** 2
const MINUTE = 60_000

function disk(fields: Partial<Disk>): Disk {
    return { holds: ['workspace'], path: '/w', total: 500 * GIB, free: 200 * GIB, floor: 2 * GIB, ...fields }
}

describe('bytesText', () => {
    it('reads in binary units, with a decimal under ten', () => {
        expect(bytesText(512)).toBe('512 B')
        expect(bytesText(268 * MIB)).toBe('268 MiB')
        expect(bytesText(9.84 * GIB)).toBe('9.8 GiB')
        expect(bytesText(412 * GIB)).toBe('412 GiB')
        expect(bytesText(2 * 1024 * GIB)).toBe('2.0 TiB')
    })
})

describe('diskPressure', () => {
    it("is critical under the tick's floor, where no tick runs the overseer", () => {
        expect(diskPressure(disk({ free: 1.5 * GIB, floor: 2 * GIB }))).toBe('critical')
    })

    it('is critical under a gigabyte on a disk with no floor', () => {
        expect(diskPressure(disk({ holds: ['temp'], free: 512 * MIB, floor: null }))).toBe('critical')
    })

    it('is high under ten gigabytes, or under twice a floor larger than that', () => {
        expect(diskPressure(disk({ free: 8 * GIB }))).toBe('high')
        expect(diskPressure(disk({ free: 15 * GIB, floor: 10 * GIB }))).toBe('high')
        expect(diskPressure(disk({ free: 12 * GIB }))).toBe('ok')
    })
})

describe('memoryPressure', () => {
    it('reads the share still available, and is fine when the operating system does not say', () => {
        const total = 64 * GIB
        expect(memoryPressure({ total, available: 2 * GIB, swap_total: null, swap_free: null })).toBe('critical')
        expect(memoryPressure({ total, available: 6 * GIB, swap_total: null, swap_free: null })).toBe('high')
        expect(memoryPressure({ total, available: null, swap_total: null, swap_free: null })).toBe('ok')
    })
})

describe('the load', () => {
    it('reads as a share of the cores, and not at all without them', () => {
        expect(coreShare(3, 12)).toBe(0.25)
        expect(coreShare(15, 12)).toBe(1.25)
        expect(coreShare(3, null)).toBeNull()
    })

    it('heads somewhere once the last minute moves a tenth of the cores off the quarter hour', () => {
        expect(loadTrend({ cores: 12, load: [6, 4, 4.5], time: null })).toBe('rising')
        expect(loadTrend({ cores: 12, load: [2, 3, 3.5], time: null })).toBe('falling')
        expect(loadTrend({ cores: 12, load: [2.41, 1.87, 1.52], time: null })).toBe('steady')
        expect(loadTrend({ cores: null, load: [1, 1, 0.4], time: null })).toBe('rising')
        expect(loadTrend({ cores: 2, load: [0.9, 0.7, 0.6], time: null })).toBe('steady')
        expect(loadTrend({ cores: 12, load: null, time: null })).toBeNull()
    })
})

describe('the header readout', () => {
    it('says the host is ok when nothing is under pressure', () => {
        expect(hostReadout(mockHost())).toBe('host ok')
        expect(hostPressure(mockHost())).toBe('ok')
        expect(concerns(mockHost())).toEqual([])
    })

    it('names the worst concern: a disk under the floor before a busy machine', () => {
        const host = mockHost({
            cpu: { cores: 4, load: [6, 5, 4], time: null },
            disks: [disk({ holds: ['workspace', 'journal'], free: GIB })],
        })

        expect(hostReadout(host)).toBe('disk low')
        expect(hostPressure(host)).toBe('critical')
        expect(concerns(host).map((c) => c.text)).toEqual([
            "1.0 GiB free where the workspace and the journal are, under the tick's floor of 2.0 GiB: no tick runs " +
                'the overseer',
            'load at 125% of 4 cores over five minutes: work waits for a processor',
        ])
    })

    it('calls a saturated machine busy, never broken', () => {
        const host = mockHost({ cpu: { cores: 2, load: [3, 2, 1], time: null } })

        expect(hostReadout(host)).toBe('host busy')
        expect(hostPressure(host)).toBe('high')
    })
})

describe('diskHolds', () => {
    it('lists what a disk keeps in words', () => {
        expect(diskHolds(disk({ holds: ['workspace', 'journal', 'temp'] }))).toBe(
            'the workspace, the journal and the temporary directory',
        )
        expect(diskHolds(disk({ holds: ['temp'] }))).toBe('the temporary directory')
    })
})

// A disk's free space read once a minute for an hour, `at(minute)` at each.
function freeOver(at: (minute: number) => number): Trend {
    const points = Array.from({ length: 61 }, (_, minute) => ({ at: minute * MINUTE, value: at(minute) }))
    const values = points.map((p) => p.value)
    return { points, runs: [points], start: 0, end: 60 * MINUTE, peak: Math.max(...values), low: Math.min(...values) }
}

describe('fillsIn', () => {
    it('says how long until full at the rate of the last hour', () => {
        // 30 GiB gone in the hour, 90 GiB left: three hours more.
        const left = fillsIn(freeOver((m) => (120 - m / 2) * GIB))
        expect(left).not.toBeNull()
        expect(fillsInText(left ?? 0)).toBe('full in about 3 h at this rate')
        expect(fillsInText(25 * MINUTE)).toBe('full in about 25 min at this rate')
    })

    it('says nothing while the disk is not filling, or would last past a day', () => {
        expect(fillsIn(freeOver(() => 100 * GIB))).toBeNull()
        expect(fillsIn(freeOver((m) => (100 + m) * GIB))).toBeNull()
        // The mock's workspace disk: 1.6 GiB written over the hour, 412 GiB left, weeks away.
        expect(fillsIn(freeOver((m) => (413.6 - (1.6 * m) / 60) * GIB))).toBeNull()
    })

    it('reads a dip a build cleared after as no trend', () => {
        expect(fillsIn(freeOver((m) => (27 - (m > 40 && m < 55 ? 11 : 0)) * GIB))).toBeNull()
    })
})

describe('concerns', () => {
    it('says the way out of each, naming the key that sets it', () => {
        const pressed = mockHost({
            disks: [disk({ free: 1.5 * GIB, floor: 2 * GIB })],
            memory: { total: 64 * GIB, available: 2 * GIB, swap_total: 0, swap_free: 0 },
            cpu: { cores: 4, load: [5, 5, 5], time: null },
        })
        const found = concerns(pressed)
        expect(found.map((c) => c.what)).toEqual(['disk', 'memory', 'load'])
        expect(found[0]?.text).toBe(
            "1.5 GiB free where the workspace is, under the tick's floor of 2.0 GiB: no tick runs the overseer",
        )
        expect(found[0]?.way).toContain('`loop.min_free_disk_mib`')
        expect(found[1]?.text).toContain('a new agent or build may swap')
        expect(found[2]?.way).toContain('`capacity.max_workers`')
    })
})
