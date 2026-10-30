import { describe, expect, it } from 'vitest'

import { mockHost } from '@/api/mocks'
import type { Disk } from '@/api/types'

import {
    bytesText,
    concerns,
    coreShare,
    diskHolds,
    diskPressure,
    hostPressure,
    hostReadout,
    loadTrend,
    memoryPressure,
} from './host'

const GIB = 1024 ** 3
const MIB = 1024 ** 2

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
