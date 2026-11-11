import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ToastContext } from '@/hooks/use-toast'
import { blockSlots, newSlotId } from '@/lib/block-slots'
import { diagramPng } from '@/lib/diagram-picture'
import { saveFile } from '@/lib/save-file'
import type { NewToast } from '@/lib/toasts'

import { PlanBlockActions } from './block-actions'

// A canvas draws nothing in happy-dom: a picture is made as a PNG in a real browser alone (e2e/plan-diagrams.spec.ts).
vi.mock(import('@/lib/diagram-picture'), async (importOriginal) => ({
    ...(await importOriginal()),
    diagramPng: vi.fn<typeof diagramPng>(() => Promise.resolve(new Blob(['png'], { type: 'image/png' }))),
}))
vi.mock(import('@/lib/save-file'), async (importOriginal) => ({
    ...(await importOriginal()),
    saveFile: vi.fn<typeof saveFile>(),
}))

let toasts: NewToast[] = []

// A diagram's picture, drawn as a `kind` diagram.
interface Picture {
    svg: string
    kind: string
}

// A plan's document, as the editor that owns it, with the room its diagrams keep for their actions.
function planDocument(): {
    owner: object
    put: (source: string, drawn?: Picture) => HTMLElement
    remove: (slot: HTMLElement) => void
} {
    const owner = {}
    const slots = blockSlots(owner)
    const ids = new Map<HTMLElement, number>()
    return {
        owner,
        put: (source, drawn) => {
            const slot = document.createElement('div')
            document.body.append(slot)
            const id = newSlotId()
            ids.set(slot, id)
            act(() => {
                slots.put({ id, kind: 'diagram', slot, source, drawn })
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
            <PlanBlockActions owner={owner} name="ABC-1-plan-2" />
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
    vi.mocked(saveFile).mockClear()
    vi.mocked(diagramPng).mockClear()
})

// Opens the picture's menu in `slot`, as a click on its button does.
function openPictureMenu(slot: HTMLElement): void {
    const trigger = within(slot).getByRole('button', { name: 'Copy or save the picture' })
    fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })
}

// Lets the promises an action awaits settle, and React render what they did.
async function settle(): Promise<void> {
    await act(async () => {
        await Promise.resolve()
        await Promise.resolve()
    })
}

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

    it("copy a code block's code from its room", async () => {
        const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
        const owner = {}
        renderActions(owner)
        const slot = document.createElement('div')
        document.body.append(slot)
        act(() => {
            blockSlots(owner).put({ id: newSlotId(), kind: 'code', slot, text: 'make lint' })
        })
        fireEvent.click(within(slot).getByRole('button', { name: 'Copy code' }))
        await settle()
        expect(write).toHaveBeenCalledWith('make lint')
    })

    it('go when their diagram does', () => {
        const plan = planDocument()
        renderActions(plan.owner)
        const slot = plan.put('flowchart LR\n    A --> B')
        expect(screen.getAllByRole('button')).toHaveLength(1)
        plan.remove(slot)
        expect(screen.queryAllByRole('button')).toHaveLength(0)
    })

    it('offer no picture until it is drawn', () => {
        const plan = planDocument()
        renderActions(plan.owner)
        const slot = plan.put('flowchart LR\n    A --> B')
        expect(within(slot).queryByRole('button', { name: 'Copy or save the picture' })).toBeNull()
    })

    it("save a drawn one's picture as a PNG named for its plan, its kind, and its place among the plan's", async () => {
        const plan = planDocument()
        renderActions(plan.owner)
        const first = plan.put('sequenceDiagram\n    A->>B: hi', { svg: '<svg>one</svg>', kind: 'sequence' })
        const second = plan.put('flowchart LR\n    A --> B', { svg: '<svg>two</svg>', kind: 'flowchart-v2' })

        openPictureMenu(second)
        fireEvent.click(await screen.findByRole('menuitem', { name: 'Save as PNG' }))
        await settle()
        expect(diagramPng).toHaveBeenCalledWith('<svg>two</svg>', expect.any(String))
        expect(saveFile).toHaveBeenCalledWith(expect.any(Blob), 'ABC-1-plan-2-flowchart-2.png')
        expect(toasts).toEqual([
            { title: 'Saved the diagram as a PNG', detail: 'ABC-1-plan-2-flowchart-2.png', tone: 'done' },
        ])
        expect(within(first).getByRole('button', { name: 'Copy or save the picture' })).toBeDefined()
    })

    it("save a drawn one's picture as an SVG, cut down to what canopy keeps, on a background", async () => {
        const plan = planDocument()
        renderActions(plan.owner)
        const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><g onclick="go()"><rect/></g></svg>'
        const slot = plan.put('erDiagram\n    A ||--o{ B : has', { svg, kind: 'er' })

        openPictureMenu(slot)
        fireEvent.click(await screen.findByRole('menuitem', { name: 'Save as SVG' }))
        const [blob, name] = vi.mocked(saveFile).mock.lastCall ?? []
        expect(name).toBe('ABC-1-plan-2-er-1.svg')
        expect(blob?.type).toBe('image/svg+xml')
        const saved = (await blob?.text()) ?? ''
        expect(saved).toContain('<rect x="0" y="0" width="4" height="4"')
        expect(saved).not.toContain('onclick')
        expect(toasts).toEqual([
            { title: 'Saved the diagram as an SVG', detail: 'ABC-1-plan-2-er-1.svg', tone: 'done' },
        ])
    })

    it("copy a drawn one's picture as a PNG on the clipboard", async () => {
        vi.stubGlobal(
            'ClipboardItem',
            class {
                readonly items: Record<string, Promise<Blob>>
                constructor(items: Record<string, Promise<Blob>>) {
                    this.items = items
                }
            },
        )
        const write = vi.spyOn(navigator.clipboard, 'write').mockResolvedValue()
        const plan = planDocument()
        renderActions(plan.owner)
        const slot = plan.put('stateDiagram-v2\n    [*] --> A', { svg: '<svg>state</svg>', kind: 'stateDiagram' })

        openPictureMenu(slot)
        fireEvent.click(await screen.findByRole('menuitem', { name: 'Copy as image' }))
        await settle()
        const [items] = write.mock.lastCall ?? [[]]
        expect(Object.keys((items[0] as unknown as { items: object }).items)).toEqual(['image/png'])
        expect(toasts).toEqual([
            { title: 'Copied the diagram as an image', detail: 'ABC-1-plan-2-state-1.png', tone: 'done' },
        ])
    })

    it('offer no copy of the picture where the page cannot reach the clipboard', async () => {
        vi.stubGlobal('isSecureContext', false)
        const plan = planDocument()
        renderActions(plan.owner)
        const slot = plan.put('flowchart LR\n    A --> B', { svg: '<svg/>', kind: 'flowchart-v2' })
        openPictureMenu(slot)
        expect(await screen.findByRole('menuitem', { name: 'Save as PNG' })).toBeDefined()
        expect(screen.queryByRole('menuitem', { name: 'Copy as image' })).toBeNull()
    })
})
