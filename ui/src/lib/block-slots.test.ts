import { describe, expect, it, vi } from 'vitest'

import { blockSlots, newSlotId } from './block-slots'
import type { BlockSlot } from './block-slots'

// A diagram's room for its actions, holding `source`.
function diagram(id: number, source: string): BlockSlot {
    return { id, kind: 'diagram', slot: document.createElement('div'), source, drawn: undefined }
}

describe("a document's blocks with room for their actions", () => {
    it('are kept per document, the same list until one changes', () => {
        const owner = {}
        const slots = blockSlots(owner)
        expect(blockSlots(owner)).toBe(slots)
        expect(blockSlots({})).not.toBe(slots)
        const before = slots.snapshot()
        expect(slots.snapshot()).toBe(before)
        slots.put(diagram(newSlotId(), 'flowchart LR'))
        expect(slots.snapshot()).not.toBe(before)
    })

    it('take a block in place of the one of its id, and drop one removed, telling who listens each time', () => {
        const slots = blockSlots({})
        const heard = vi.fn<() => void>()
        const stop = slots.subscribe(heard)
        const [first, second] = [newSlotId(), newSlotId()]
        slots.put(diagram(first, 'flowchart LR'))
        slots.put(diagram(second, 'sequenceDiagram'))
        slots.put(diagram(first, 'flowchart TD'))
        expect(slots.snapshot().map((block) => [block.id, block.source])).toEqual([
            [first, 'flowchart TD'],
            [second, 'sequenceDiagram'],
        ])
        slots.remove(first)
        expect(slots.snapshot().map((block) => block.id)).toEqual([second])
        expect(heard).toHaveBeenCalledTimes(4)
        stop()
        slots.remove(second)
        expect(heard).toHaveBeenCalledTimes(4)
    })

    it('are given ids never given before', () => {
        expect(newSlotId()).not.toBe(newSlotId())
    })
})
