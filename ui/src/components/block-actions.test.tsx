import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ToastContext } from '@/hooks/use-toast'
import { blockSlots, newSlotId } from '@/lib/block-slots'
import type { NewToast } from '@/lib/toasts'

import { PlanBlockActions } from './block-actions'

let toasts: NewToast[] = []

// A plan's document, as the editor that owns it, with the room its diagrams keep for their actions.
function planDocument(): { owner: object; put: (source: string) => HTMLElement; remove: (slot: HTMLElement) => void } {
    const owner = {}
    const slots = blockSlots(owner)
    const ids = new Map<HTMLElement, number>()
    return {
        owner,
        put: (source) => {
            const slot = document.createElement('div')
            document.body.append(slot)
            const id = newSlotId()
            ids.set(slot, id)
            act(() => {
                slots.put({ id, kind: 'diagram', slot, source })
            })
            return slot
        },
        remove: (slot) => {
            act(() => {
                slots.remove(ids.get(slot) ?? 0)
            })
        },
    }
}

function renderActions(owner: object) {
    return render(
        <ToastContext
            value={(toast) => {
                toasts.push(toast)
            }}
        >
            <PlanBlockActions owner={owner} />
        </ToastContext>,
    )
}

beforeEach(() => {
    toasts = []
    vi.stubGlobal('isSecureContext', true)
})

afterEach(() => {
    cleanup()
    document.body.replaceChildren()
})

describe("a plan's diagram's actions", () => {
    it("are drawn in each diagram's room for them, and copy its Mermaid source", async () => {
        const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
        const plan = planDocument()
        renderActions(plan.owner)
        const first = plan.put('flowchart LR\n    A --> B')
        const second = plan.put('sequenceDiagram\n    A->>B: hi')

        fireEvent.click(within(second).getByRole('button', { name: 'Copy Mermaid source' }))
        await act(async () => {
            await Promise.resolve()
        })
        expect(write).toHaveBeenCalledWith('sequenceDiagram\n    A->>B: hi')
        expect(toasts).toEqual([
            { title: 'Copied Mermaid source', detail: 'sequenceDiagram\n    A->>B: hi', tone: 'done' },
        ])
        expect(within(first).getByRole('button', { name: 'Copy Mermaid source' })).toBeDefined()
    })

    it('go when their diagram does', () => {
        const plan = planDocument()
        renderActions(plan.owner)
        const slot = plan.put('flowchart LR\n    A --> B')
        expect(screen.getAllByRole('button')).toHaveLength(1)
        plan.remove(slot)
        expect(screen.queryAllByRole('button')).toHaveLength(0)
    })
})
